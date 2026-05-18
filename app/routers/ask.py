"""Ask StockSense — NL → SQL → natural-language answer chat endpoint.

POST /api/ask streams Server-Sent Events:
  event: token   data: {"text": "..."}            ← (internal) SQL tokens — FE ignores
  event: sql     data: {"sql": "<full sql>"}      ← (internal) once the SQL finishes
  event: result  data: {"columns": [...], "rows": [[...]]}
  event: answer  data: {"text": "..."}            ← natural-language answer, streamed
  event: done    data: {"log_id": N, "duration_ms": N, "row_count": N, "status": "ok"}
  event: error   data: {"message": "...", "log_id": N, "status": "..."}

The `token` and `sql` events still fire — the SQL is preserved in
query_logs.generated_sql for audit — but the chat UI doesn't render
them. Users see only the streamed `answer` text + the result table.

Every turn is persisted in query_logs before the stream closes
(successful or not). The audit table doubles as the per-user
conversation history surfaced via GET /api/ask/history.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.executor import ExecError, ExecTimeout, execute_safe
from app.ai.llm import LLMError, has_real_llm, stream_answer, stream_sql
from app.ai.prompt import build_messages
from app.core.db import engine
from app.deps import get_current_user, get_db
from app.models.query_log import QueryLog, QueryStatus
from app.models.user import User
from app.schemas.ask import AskIn, QueryLogOut

router = APIRouter(prefix="/api/ask", tags=["ask"])


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


@router.post("")
async def ask(
    payload: AskIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    async def stream() -> AsyncIterator[bytes]:
        question = payload.question.strip()

        # Step 1 — open a stub log row up front so we have an id to ship
        # back to the UI in every error path.
        log = QueryLog(
            user_id=user.id,
            question=question,
            generated_sql=None,
            status=QueryStatus.llm_error,
            duration_ms=0,
        )
        db.add(log)
        db.flush()
        db.commit()

        # Step 2 — call the LLM, stream tokens to the FE, accumulate full SQL.
        messages = build_messages(question, engine)
        sql_buffer = ""
        try:
            async for token in stream_sql(messages, question):
                sql_buffer += token
                yield _sse("token", {"text": token})
        except LLMError as exc:
            log.error_message = str(exc)
            log.status = QueryStatus.llm_error
            db.commit()
            yield _sse("error", {"message": str(exc), "log_id": log.id, "status": log.status.value})
            return

        sql_text = _strip_markdown_fence(sql_buffer)
        log.generated_sql = sql_text
        db.commit()
        yield _sse("sql", {"sql": sql_text})

        # Step 3 — safety validate.
        from app.ai.safety import validate

        result = validate(sql_text)
        if result.safe_sql is None:
            msg = "; ".join(result.violations)
            log.status = QueryStatus.safety_rejected
            log.error_message = msg
            db.commit()
            yield _sse(
                "error",
                {"message": msg, "log_id": log.id, "status": log.status.value},
            )
            return

        log.generated_sql = result.safe_sql
        db.commit()

        # Step 4 — execute as the read-only role, with RLS scoped to
        # this user (Postgres filters every owner-tracked table by
        # owner_id = user.id even if the LLM forgets a WHERE clause).
        try:
            columns, rows, duration_ms = execute_safe(result.safe_sql, user.id)
        except ExecTimeout as exc:
            log.status = QueryStatus.timeout
            log.error_message = str(exc)
            db.commit()
            yield _sse(
                "error",
                {"message": str(exc), "log_id": log.id, "status": log.status.value},
            )
            return
        except ExecError as exc:
            log.status = QueryStatus.exec_error
            log.error_message = str(exc)
            db.commit()
            yield _sse(
                "error",
                {"message": str(exc), "log_id": log.id, "status": log.status.value},
            )
            return

        log.status = QueryStatus.ok
        log.row_count = len(rows)
        log.duration_ms = duration_ms
        db.commit()

        yield _sse("result", {"columns": columns, "rows": rows})

        # Step 5 — synthesize a 1-2 sentence natural-language answer
        # over the rows. The user sees this; the SQL is hidden in the UI.
        # LLM failures here are non-fatal: log the message, still emit done.
        answer_buffer = ""
        try:
            async for chunk in stream_answer(question, result.safe_sql, columns, rows):
                answer_buffer += chunk
                yield _sse("answer", {"text": chunk})
        except LLMError as exc:
            # Don't blow up the whole turn — the user still has the data
            # table. Record the failure so an admin can debug it later.
            log.error_message = f"answer synthesis failed: {exc}"
        finally:
            log.answer_text = answer_buffer or None
            db.commit()

        yield _sse(
            "done",
            {
                "log_id": log.id,
                "duration_ms": duration_ms,
                "row_count": len(rows),
                "status": log.status.value,
                "llm": "openrouter" if has_real_llm() else "stub",
            },
        )

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/history", response_model=list[QueryLogOut])
def history(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[QueryLog]:
    return list(
        db.scalars(
            select(QueryLog)
            .where(QueryLog.user_id == user.id)
            .order_by(QueryLog.created_at.desc())
            .limit(limit)
        )
    )


@router.get("/{log_id}", response_model=QueryLogOut)
def get_turn(
    log_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QueryLog:
    log = db.get(QueryLog, log_id)
    if log is None or log.user_id != user.id:
        from fastapi import HTTPException, status as st

        raise HTTPException(st.HTTP_404_NOT_FOUND, "turn not found")
    return log


def _strip_markdown_fence(s: str) -> str:
    """Defensive: if the LLM wrapped the SQL in ```sql … ``` despite
    the prompt instructions, strip the fence."""
    s = s.strip()
    if s.startswith("```"):
        s = s.lstrip("`")
        # Drop optional language tag on the first line.
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1 :]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip().rstrip(";").strip()
