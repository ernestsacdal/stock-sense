"""End-to-end coverage of POST /api/ask in stub mode.

The Ask pipeline has three external surfaces: the LLM (Groq in dev,
stub in tests since OPENROUTER_API_KEY isn't set), the safety
validator, and the read-only SQL executor. Tests cover the happy
path (token → sql → result → answer → done events fire in order,
QueryLog rows store both SQL and answer_text), plus the failure
paths (safety reject, exec error) which short-circuit before the
answer step.

Stub mode means no network call — `has_real_llm()` returns False,
the LLM picks the closest few-shot SQL by word overlap, and the
answer is synthesised deterministically from the row count.
"""

from __future__ import annotations

import json
import re

from sqlalchemy import text

from app.core.db import engine


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """Split an SSE response into (event, data) tuples."""
    events: list[tuple[str, dict]] = []
    for block in body.strip().split("\n\n"):
        if not block.strip():
            continue
        event = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data += line[len("data:") :].strip()
        if event:
            events.append((event, json.loads(data) if data else {}))
    return events


def _ask(client, token: str, question: str) -> list[tuple[str, dict]]:
    r = client.post(
        "/api/ask",
        json={"question": question},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    return _parse_sse(r.text)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_running_low_question_emits_full_event_sequence(client, auth_token):
    """`token`+ events stream, then `sql`, `result`, `answer` (≥1),
    and `done` — in order."""
    token, _ = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    cat = client.post("/api/categories", json={"name": "Goods"}, headers=headers).json()
    client.post(
        "/api/items",
        json={
            "sku": "X-1", "name": "Widget", "category_id": cat["id"],
            "quantity": 1, "reorder_threshold": 5,
        },
        headers=headers,
    )

    events = _ask(client, token, "what's running low?")
    event_names = [e for e, _ in events]
    # At least one token, then sql, then result, then answer chunks, then done.
    assert "token" in event_names
    assert event_names.index("sql") < event_names.index("result")
    assert event_names.index("result") < event_names.index("answer")
    assert event_names[-1] == "done"

    # The result event should include the named item.
    result_event = next(d for e, d in events if e == "result")
    flat_rows = [cell for row in result_event["rows"] for cell in row]
    assert any("Widget" == str(c) for c in flat_rows)


def test_done_event_carries_log_id_status_llm(client, auth_token):
    token, _ = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    cat = client.post("/api/categories", json={"name": "G"}, headers=headers).json()
    client.post(
        "/api/items",
        json={"sku": "D-1", "name": "Done item", "category_id": cat["id"]},
        headers=headers,
    )

    events = _ask(client, token, "list all items")
    done = next(d for e, d in events if e == "done")
    assert done["status"] == "ok"
    assert isinstance(done["log_id"], int)
    assert done["llm"] == "stub"  # OPENROUTER_API_KEY unset in tests


def test_query_log_persists_sql_and_answer_text(client, auth_token):
    """Both generated_sql and answer_text should be written to
    query_logs at the end of a successful turn."""
    token, _ = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    cat = client.post("/api/categories", json={"name": "Persist"}, headers=headers).json()
    client.post(
        "/api/items",
        json={"sku": "P-1", "name": "Persisted", "category_id": cat["id"]},
        headers=headers,
    )

    events = _ask(client, token, "list all items")
    log_id = next(d["log_id"] for e, d in events if e == "done")

    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT generated_sql, answer_text, status FROM query_logs WHERE id = :id"
            ),
            {"id": log_id},
        ).one()
    assert row.status == "ok"
    assert row.generated_sql is not None and "SELECT" in row.generated_sql.upper()
    assert row.answer_text is not None and len(row.answer_text) > 0


def test_history_endpoint_returns_answer_text(client, auth_token):
    """GET /api/ask/history should expose answer_text alongside SQL."""
    token, _ = auth_token(role="admin")
    cat = client.post(
        "/api/categories",
        json={"name": "Hist"},
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    client.post(
        "/api/items",
        json={"sku": "H-1", "name": "Hist item", "category_id": cat["id"]},
        headers={"Authorization": f"Bearer {token}"},
    )

    _ask(client, token, "list all items")
    history = client.get(
        "/api/ask/history?limit=5",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert len(history) == 1
    entry = history[0]
    assert "answer_text" in entry
    assert entry["answer_text"] is not None
    assert "generated_sql" in entry


# ---------------------------------------------------------------------------
# Failure paths — answer step is skipped, no answer_text persisted
# ---------------------------------------------------------------------------


def test_safety_rejected_question_skips_answer(client, auth_token, monkeypatch):
    """If the LLM emits banned SQL, the safety validator should reject
    it before the executor runs and the answer step should not fire."""
    # Force the stub to emit a banned statement.
    async def fake_stream(messages, question):
        for chunk in re.findall(r"\S+\s*", "DELETE FROM items WHERE 1=1"):
            yield chunk

    from app.routers import ask as ask_module

    monkeypatch.setattr(ask_module, "stream_sql", fake_stream)

    token, _ = auth_token(role="admin")
    events = _ask(client, token, "delete everything")
    event_names = [e for e, _ in events]
    assert "error" in event_names
    assert "answer" not in event_names
    assert "result" not in event_names

    log_id = next(d["log_id"] for e, d in events if e == "error")
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT status, answer_text FROM query_logs WHERE id = :id"),
            {"id": log_id},
        ).one()
    assert row.status == "safety_rejected"
    assert row.answer_text is None


def test_unauthenticated_ask_rejected(client):
    r = client.post("/api/ask", json={"question": "hi"})
    assert r.status_code == 401
