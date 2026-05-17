"""End-to-end happy-path smoke that exercises every backend endpoint
in one linear flow. Fast-failing canary that catches integration
regressions the per-area tests can miss (e.g. a restock that updates
the item but breaks the dashboard summary).

Walks: register -> create-everything -> opening qty -> restock ->
issue -> list/filter -> dashboard summary + value-history + activity
-> patch item -> patch profile -> archive -> include-archived list ->
Ask AI SSE stream -> QueryLog persistence.
"""

from __future__ import annotations

import json
from datetime import date, timedelta


def _hdrs(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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


def test_full_flow_walks_every_endpoint(client, auth_token):
    """One test, many steps — each asserts the right thing, then hands
    state to the next step. Run takes ~2s."""
    token, user = auth_token(email="smoke@stocksense.dev", role="admin")
    H = _hdrs(token)

    # --- 1. Bootstrap workspace ---

    cat = client.post("/api/categories", json={"name": "Beans"}, headers=H).json()
    sup = client.post(
        "/api/suppliers",
        json={"name": "Bean Supply", "contact": "rep@bean.dev"},
        headers=H,
    ).json()
    loc = client.post(
        "/api/locations",
        json={"name": "Storeroom"},
        headers=H,
    ).json()
    assert cat["id"] and sup["id"] and loc["id"]

    # --- 2. Create item with opening qty + every optional field ---

    expiry = (date.today() + timedelta(days=60)).isoformat()
    create_body = {
        "sku": "BEAN-1",
        "name": "Espresso Beans",
        "category_id": cat["id"],
        "supplier_id": sup["id"],
        "location_id": loc["id"],
        "reorder_threshold": 5,
        "quantity": 10,
        "unit_cost": "18.50",
        "expiry_date": expiry,
        "notes": "Order Friday only",
    }
    item = client.post("/api/items", json=create_body, headers=H).json()
    item_id = item["id"]
    assert item["quantity"] == 10
    assert item["unit_cost"] == "18.50"
    assert item["notes"] == "Order Friday only"

    # The create endpoint should auto-log an 'added' movement for the
    # opening qty.
    movs = client.get(f"/api/movements?item_id={item_id}", headers=H).json()
    assert len(movs) == 1
    assert movs[0]["type"] == "added"
    assert movs[0]["quantity_delta"] == 10
    assert movs[0]["user_id"] == user["id"]

    # --- 3. Restock — increments qty, logs 'received' movement ---

    r = client.post(
        f"/api/items/{item_id}/restock",
        json={"quantity": 5},
        headers=H,
    )
    assert r.status_code == 200
    assert r.json()["quantity"] == 15

    # --- 4. Issue — decrements qty, logs 'issued' movement ---

    r = client.post(
        f"/api/items/{item_id}/issue",
        json={"quantity": 3, "notes": "to customer"},
        headers=H,
    )
    assert r.status_code == 200
    assert r.json()["quantity"] == 12

    # All three movement types present, newest first.
    movs = client.get(f"/api/movements?item_id={item_id}", headers=H).json()
    assert [m["type"] for m in movs] == ["issued", "received", "added"]
    assert movs[0]["quantity_delta"] == -3
    assert movs[0]["notes"] == "to customer"

    # --- 5. List filters ---

    by_q = client.get("/api/items?q=Espresso", headers=H).json()
    assert any(i["id"] == item_id for i in by_q)
    by_cat = client.get(f"/api/items?category_id={cat['id']}", headers=H).json()
    assert any(i["id"] == item_id for i in by_cat)
    by_loc = client.get(f"/api/items?location_id={loc['id']}", headers=H).json()
    assert any(i["id"] == item_id for i in by_loc)
    by_sup = client.get(f"/api/items?supplier_id={sup['id']}", headers=H).json()
    assert any(i["id"] == item_id for i in by_sup)
    ok_only = client.get("/api/items?stock_status=ok", headers=H).json()
    assert any(i["id"] == item_id for i in ok_only)

    # Summary row should carry location_name from the outer join.
    listed = next(i for i in by_loc if i["id"] == item_id)
    assert listed["location_name"] == "Storeroom"
    assert listed["on_hand"] == 12

    # --- 6. Item detail ---

    detail = client.get(f"/api/items/{item_id}", headers=H).json()
    assert detail["notes"] == "Order Friday only"
    assert detail["expiry_date"] == expiry
    assert detail["location_id"] == loc["id"]

    # --- 7. Dashboard summary reflects the live state ---

    summary = client.get("/api/dashboard/summary", headers=H).json()
    # 12 units × 18.50 = 222.00
    assert float(summary["total_value"]) == 222.0
    assert summary["active_skus"] == 1
    # Expiry is +60d, outside the 30d window.
    assert summary["expiring_30d_count"] == 0
    # 12 > threshold 5 → no low-stock alert.
    assert summary["low_stock_count"] == 0
    assert summary["low_stock_critical"] == 0

    # --- 8. Value history — 7 daily points, newest last ---

    history = client.get("/api/dashboard/value-history?days=7", headers=H).json()
    assert len(history) == 7
    assert history[-1]["date"] == date.today().isoformat()

    # --- 9. Activity feed — three movements, newest first ---

    activity = client.get("/api/dashboard/activity?limit=10", headers=H).json()
    assert len(activity) == 3
    assert [a["type"] for a in activity] == ["issued", "received", "added"]
    assert activity[0]["item_name"] == "Espresso Beans"
    assert activity[0]["user_email"] == user["email"]

    # --- 10. PATCH item: clear notes via null ---

    patched = client.patch(
        f"/api/items/{item_id}",
        json={"notes": None},
        headers=H,
    ).json()
    assert patched["notes"] is None

    # --- 11. PATCH /me: update business_name ---

    me = client.patch(
        "/api/auth/me",
        json={"business_name": "Joe's Cafe"},
        headers=H,
    ).json()
    assert me["business_name"] == "Joe's Cafe"

    # --- 12. Archive: item drops from default list, returns with flag ---

    archived = client.delete(f"/api/items/{item_id}", headers=H).json()
    assert archived["archived_at"] is not None

    default_list = client.get("/api/items", headers=H).json()
    assert not any(i["id"] == item_id for i in default_list)

    with_archived = client.get("/api/items?include_archived=true", headers=H).json()
    assert any(i["id"] == item_id for i in with_archived)

    # --- 13. Ask AI: SSE stream + QueryLog persistence ---

    ask = client.post(
        "/api/ask",
        json={"question": "list all items"},
        headers=H,
    )
    assert ask.status_code == 200
    events = _parse_sse(ask.text)
    event_names = [e for e, _ in events]
    # Token + sql + result + answer + done — full sequence.
    assert "token" in event_names
    assert "sql" in event_names
    assert "result" in event_names
    assert "answer" in event_names
    assert event_names[-1] == "done"

    done = next(d for e, d in events if e == "done")
    assert done["status"] == "ok"
    log_id = done["log_id"]

    # The audit log should carry both the SQL and the synthesised answer.
    turn = client.get(f"/api/ask/{log_id}", headers=H).json()
    assert turn["generated_sql"] is not None and "SELECT" in turn["generated_sql"].upper()
    assert turn["answer_text"] is not None and len(turn["answer_text"]) > 0
    assert turn["status"] == "ok"
