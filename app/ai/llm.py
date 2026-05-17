"""OpenRouter LLM client wrapper.

Two stages:

- `stream_sql(messages, question)` — natural language → SQL. The model
  reads the schema + few-shots in `messages` and emits a single SELECT.
- `stream_answer(question, sql, columns, rows)` — SQL results → 1–2
  sentence plain-English answer. Runs after the SQL executes. The
  user sees this; the SQL itself is hidden in the UI.

When OPENROUTER_API_KEY is empty (no-cost local mode), both stages
fall back to deterministic stubs. The stub for `stream_sql` picks
the closest few-shot example by word overlap; the stub for
`stream_answer` synthesises a short summary from the row count + first
row. End-to-end testable without a key, and the OpenRouter path kicks
in unchanged the moment the key is set.

OpenRouter is OpenAI-compatible — we use the `openai` SDK pointed at
https://openrouter.ai/api/v1.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any, cast

from app.ai.prompt import FEW_SHOTS
from app.core.config import get_settings

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class LLMError(Exception):
    pass


def has_real_llm() -> bool:
    return bool(get_settings().openrouter_api_key.strip())


def current_model() -> str:
    """Used by the audit log + the SSE `done` event so the UI / DB
    knows which model produced a given answer."""
    return get_settings().openrouter_model


# ---------------------------------------------------------------------------
# Stage 1: NL → SQL
# ---------------------------------------------------------------------------


async def stream_sql(messages: list[dict[str, str]], question: str) -> AsyncIterator[str]:
    """Yield the model's SQL tokens one at a time."""
    if not has_real_llm():
        async for chunk in _stub_sql_stream(question):
            yield chunk
        return

    client = _client()
    try:
        stream = await client.chat.completions.create(
            model=current_model(),
            messages=cast(list, messages),
            temperature=0.0,
            max_tokens=512,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
    except Exception as exc:  # noqa: BLE001 — bubble up the friendly message
        raise LLMError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Stage 2: results → natural language answer
# ---------------------------------------------------------------------------


_ANSWER_SYSTEM = (
    "You are a concise inventory analyst. The user asked a question; you've "
    "been given the SQL we ran plus the rows it returned.\n"
    "Write 1–2 plain-English sentences that directly answer the question, "
    "naming actual items / counts / dollar amounts from the rows. Lead with "
    "the most actionable point. Don't restate the question, don't editorialize, "
    "don't mention SQL or databases. If the result set is empty, say so plainly. "
    "If the question is conversational (greetings, thanks, etc.) and the rows "
    "are empty, reply naturally in one sentence."
)


async def stream_answer(
    question: str,
    sql: str,
    columns: list[str],
    rows: list[list[Any]],
) -> AsyncIterator[str]:
    """Yield natural-language tokens that interpret the SQL results."""
    if not has_real_llm():
        async for chunk in _stub_answer_stream(question, columns, rows):
            yield chunk
        return

    # Cap the rows handed to the LLM to bound token cost — 50 is plenty
    # for any reasonable summary and stops us posting a 1000-row table
    # into the prompt.
    capped = rows[:50]
    payload = {
        "question": question,
        "sql": sql,
        "columns": columns,
        "rows": capped,
        "row_count_total": len(rows),
        "row_count_shown": len(capped),
    }
    user_message = (
        "Question: " + question + "\n\n"
        + "Results (JSON):\n" + _safe_json(payload) + "\n\n"
        + "Write your 1–2 sentence answer:"
    )

    client = _client()
    try:
        stream = await client.chat.completions.create(
            model=current_model(),
            messages=[
                {"role": "system", "content": _ANSWER_SYSTEM},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=200,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
    except Exception as exc:  # noqa: BLE001
        raise LLMError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Stub fallbacks
# ---------------------------------------------------------------------------


async def _stub_sql_stream(question: str) -> AsyncIterator[str]:
    """Pick the few-shot whose question shares the most words with the
    input, then stream its SQL token-by-token."""
    sql = _stub_pick(question)
    chunks = re.findall(r"\S+\s*", sql)
    for chunk in chunks:
        await asyncio.sleep(0.015)
        yield chunk


async def _stub_answer_stream(
    question: str,
    columns: list[str],
    rows: list[list[Any]],
) -> AsyncIterator[str]:
    """Deterministic summary used when there's no API key. Won't be as
    nuanced as the real LLM but keeps the FE / pipeline fully wired."""
    if not rows:
        text = "No results — nothing in the inventory matched that."
    else:
        first = rows[0]
        # Try to surface a name-like first column if there is one.
        label = None
        for i, col in enumerate(columns):
            if col.lower() in {"name", "item_name"} and i < len(first):
                label = str(first[i])
                break
        more = f" (+{len(rows) - 1} more)" if len(rows) > 1 else ""
        if label:
            text = f"{len(rows)} result{'s' if len(rows) != 1 else ''}. Top: {label}{more}."
        else:
            text = f"{len(rows)} result{'s' if len(rows) != 1 else ''} returned."
    # Stream the stub text in small chunks to mimic the real cadence.
    chunks = re.findall(r"\S+\s*", text)
    for chunk in chunks:
        await asyncio.sleep(0.015)
        yield chunk


def _stub_pick(question: str) -> str:
    q_words = _words(question)
    if not q_words:
        return FEW_SHOTS[0]["sql"]
    best = (-1, FEW_SHOTS[0]["sql"])
    for example in FEW_SHOTS:
        score = len(q_words & _words(example["q"]))
        if score > best[0]:
            best = (score, example["sql"])
    return best[1]


_WORD_RE = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client():
    """Lazy import + construct the OpenAI SDK client pointed at OpenRouter."""
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise LLMError("openai SDK not installed") from exc
    return AsyncOpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=get_settings().openrouter_api_key,
    )


def _safe_json(payload: dict[str, Any]) -> str:
    """JSON-encode the payload tolerating Decimals / dates / datetimes
    that may have slipped through the executor's coercion."""
    import json
    from datetime import date, datetime
    from decimal import Decimal

    def default(o: Any) -> Any:
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return str(o)

    return json.dumps(payload, default=default, separators=(",", ":"))
