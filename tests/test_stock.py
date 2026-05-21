"""End-to-end tests for the flat-item stock model.

Items now carry quantity directly. Restock increments + logs a
StockMovement (type=received). Issue decrements + logs (type=issued)
and refuses negative. Movements are append-only — the only writes are
via restock / issue / the manual POST /api/movements endpoint.
"""

from __future__ import annotations


def _seed_item(client, token, sku: str = "TEST-001", reorder_threshold: int = 10):
    headers = {"Authorization": f"Bearer {token}"}
    cat = client.post(
        "/api/categories", json={"name": f"Cat-{sku}"}, headers=headers
    ).json()
    item = client.post(
        "/api/items",
        json={
            "sku": sku,
            "name": f"Item {sku}",
            "category_id": cat["id"],
            "reorder_threshold": reorder_threshold,
        },
        headers=headers,
    ).json()
    return item["id"]


def test_restock_increments_quantity_and_logs_movement(client, auth_token):
    token, _ = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    item_id = _seed_item(client, token)

    r = client.post(
        f"/api/items/{item_id}/restock",
        json={"quantity": 25, "unit_cost": 5.00, "notes": "first shipment"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["quantity"] == 25
    assert body["unit_cost"] == "5.00"

    movements = client.get(
        f"/api/movements?item_id={item_id}", headers=headers
    ).json()
    assert len(movements) == 1
    assert movements[0]["type"] == "received"
    assert movements[0]["quantity_delta"] == 25
    assert movements[0]["notes"] == "first shipment"


def test_restock_updates_expiry_date_when_provided(client, auth_token):
    token, _ = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    item_id = _seed_item(client, token)

    r = client.post(
        f"/api/items/{item_id}/restock",
        json={"quantity": 10, "expiry_date": "2027-01-15"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["expiry_date"] == "2027-01-15"


def test_issue_decrements_quantity_and_logs_movement(client, auth_token):
    token, _ = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    item_id = _seed_item(client, token)

    client.post(
        f"/api/items/{item_id}/restock",
        json={"quantity": 50},
        headers=headers,
    )
    r = client.post(
        f"/api/items/{item_id}/issue",
        json={"quantity": 12, "notes": "to customer"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["quantity"] == 38

    movements = client.get(
        f"/api/movements?item_id={item_id}&type=issued", headers=headers
    ).json()
    assert len(movements) == 1
    assert movements[0]["quantity_delta"] == -12


def test_issue_refuses_to_go_negative(client, auth_token):
    token, _ = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    item_id = _seed_item(client, token)

    client.post(
        f"/api/items/{item_id}/restock", json={"quantity": 5}, headers=headers
    )
    r = client.post(
        f"/api/items/{item_id}/issue", json={"quantity": 10}, headers=headers
    )
    assert r.status_code == 409
    after = client.get(f"/api/items/{item_id}", headers=headers).json()
    assert after["quantity"] == 5


def test_restock_records_submitting_user(client, auth_token):
    token, user = auth_token(email="logger@test.dev", role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    item_id = _seed_item(client, token)

    client.post(
        f"/api/items/{item_id}/restock", json={"quantity": 7}, headers=headers
    )
    movements = client.get(
        f"/api/movements?item_id={item_id}", headers=headers
    ).json()
    assert movements[0]["user_id"] == user["id"]


def test_manual_movement_endpoint_for_unusual_types(client, auth_token):
    """The manual POST /api/movements is for disposed / adjusted /
    transferred — not the day-to-day restock + issue."""
    token, _ = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    item_id = _seed_item(client, token)

    client.post(
        f"/api/items/{item_id}/restock", json={"quantity": 20}, headers=headers
    )
    r = client.post(
        "/api/movements",
        json={
            "item_id": item_id,
            "type": "disposed",
            "quantity_delta": -3,
            "notes": "spoiled",
        },
        headers=headers,
    )
    assert r.status_code == 201
    after = client.get(f"/api/items/{item_id}", headers=headers).json()
    assert after["quantity"] == 17


def test_restock_requires_authentication(client):
    r = client.post(
        "/api/items/1/restock", json={"quantity": 1}
    )
    assert r.status_code == 401


def test_archived_item_does_not_appear_in_default_list(client, auth_token):
    token, _ = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    item_id = _seed_item(client, token, sku="ARCH-001")

    listed = client.get("/api/items", headers=headers).json()
    assert any(i["id"] == item_id for i in listed)

    r = client.delete(f"/api/items/{item_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["archived_at"] is not None

    listed_after = client.get("/api/items", headers=headers).json()
    assert not any(i["id"] == item_id for i in listed_after)

    listed_with = client.get(
        "/api/items?include_archived=true", headers=headers
    ).json()
    assert any(i["id"] == item_id for i in listed_with)


def test_item_create_rejects_unknown_category(client, auth_token):
    token, _ = auth_token(role="admin")
    r = client.post(
        "/api/items",
        json={"sku": "STR-001", "name": "Bad", "category_id": 999_999},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_item_create_rejects_duplicate_sku(client, auth_token):
    token, _ = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    cat = client.post(
        "/api/categories", json={"name": "DupCat"}, headers=headers
    ).json()
    body = {"sku": "DUP-001", "name": "Dup Item", "category_id": cat["id"]}
    assert client.post("/api/items", json=body, headers=headers).status_code == 201
    body["name"] = "Dup Again"
    assert client.post("/api/items", json=body, headers=headers).status_code == 409


# --- Initial-quantity audit on item creation ------------------------------


def test_item_create_with_zero_quantity_logs_no_movement(client, auth_token):
    """Creating an item with no opening stock should not insert an 'added'
    movement — there is nothing to record."""
    token, _ = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    cat = client.post(
        "/api/categories", json={"name": "ZeroCat"}, headers=headers
    ).json()
    item = client.post(
        "/api/items",
        json={"sku": "ZERO-001", "name": "Zero", "category_id": cat["id"]},
        headers=headers,
    ).json()

    movements = client.get(
        f"/api/movements?item_id={item['id']}", headers=headers
    ).json()
    assert movements == []


def test_item_create_with_initial_quantity_logs_added_movement(client, auth_token):
    """Creating an item with quantity > 0 should log one 'added' StockMovement
    for the opening balance so the audit trail starts from the right place."""
    token, user = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    cat = client.post(
        "/api/categories", json={"name": "OpenCat"}, headers=headers
    ).json()
    item = client.post(
        "/api/items",
        json={
            "sku": "OPEN-001",
            "name": "Opening Stock",
            "category_id": cat["id"],
            "quantity": 12,
        },
        headers=headers,
    ).json()
    assert item["quantity"] == 12

    movements = client.get(
        f"/api/movements?item_id={item['id']}", headers=headers
    ).json()
    assert len(movements) == 1
    m = movements[0]
    assert m["type"] == "added"
    assert m["quantity_delta"] == 12
    assert m["user_id"] == user["id"]
    assert m["notes"] is None


# --- Location FK + filter -------------------------------------------------


def test_items_list_filters_by_location(client, auth_token):
    """GET /api/items?location_id=<id> should only return items pinned to
    that location."""
    token, _ = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    cat = client.post(
        "/api/categories", json={"name": "LocCat"}, headers=headers
    ).json()
    loc_a = client.post(
        "/api/locations", json={"name": "Storeroom A"}, headers=headers
    ).json()
    loc_b = client.post(
        "/api/locations", json={"name": "Storeroom B"}, headers=headers
    ).json()

    here = client.post(
        "/api/items",
        json={
            "sku": "LOC-A-001",
            "name": "Lives in A",
            "category_id": cat["id"],
            "location_id": loc_a["id"],
        },
        headers=headers,
    ).json()
    client.post(
        "/api/items",
        json={
            "sku": "LOC-B-001",
            "name": "Lives in B",
            "category_id": cat["id"],
            "location_id": loc_b["id"],
        },
        headers=headers,
    )

    listed = client.get(
        f"/api/items?location_id={loc_a['id']}", headers=headers
    ).json()
    ids = [row["id"] for row in listed]
    assert here["id"] in ids
    assert all(row["location_id"] == loc_a["id"] for row in listed)


def test_items_list_includes_location_name(client, auth_token):
    """The summary rows the inventory page consumes need location_name so
    the FE can render it without a second query per row."""
    token, _ = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    cat = client.post(
        "/api/categories", json={"name": "NameCat"}, headers=headers
    ).json()
    loc = client.post(
        "/api/locations", json={"name": "Cold Room"}, headers=headers
    ).json()
    client.post(
        "/api/items",
        json={
            "sku": "NAME-001",
            "name": "Named Loc",
            "category_id": cat["id"],
            "location_id": loc["id"],
        },
        headers=headers,
    )

    listed = client.get(
        f"/api/items?location_id={loc['id']}", headers=headers
    ).json()
    assert any(row["location_name"] == "Cold Room" for row in listed)


def test_item_create_with_notes_persists_them(client, auth_token):
    """Items now carry a free-form notes column for context like
    'supplier rep is Mark; orders Fri only'."""
    token, _ = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    cat = client.post(
        "/api/categories", json={"name": "NoteCat"}, headers=headers
    ).json()
    created = client.post(
        "/api/items",
        json={
            "sku": "NOTE-001",
            "name": "Has notes",
            "category_id": cat["id"],
            "notes": "frozen — keep below 4C",
        },
        headers=headers,
    ).json()
    assert created["notes"] == "frozen — keep below 4C"

    fetched = client.get(f"/api/items/{created['id']}", headers=headers).json()
    assert fetched["notes"] == "frozen — keep below 4C"


def test_item_update_can_clear_notes(client, auth_token):
    """PATCH with notes=null should wipe the field, not leave it set."""
    token, _ = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    cat = client.post(
        "/api/categories", json={"name": "ClearCat"}, headers=headers
    ).json()
    item = client.post(
        "/api/items",
        json={
            "sku": "NOTE-CLR-001",
            "name": "Clearable",
            "category_id": cat["id"],
            "notes": "to be cleared",
        },
        headers=headers,
    ).json()
    assert item["notes"] == "to be cleared"

    cleared = client.patch(
        f"/api/items/{item['id']}",
        json={"notes": None},
        headers=headers,
    ).json()
    assert cleared["notes"] is None


def test_items_list_location_name_null_for_locationless_items(client, auth_token):
    token, _ = auth_token(role="admin")
    headers = {"Authorization": f"Bearer {token}"}
    cat = client.post(
        "/api/categories", json={"name": "NoLocCat"}, headers=headers
    ).json()
    client.post(
        "/api/items",
        json={"sku": "NOLOC-001", "name": "Floating", "category_id": cat["id"]},
        headers=headers,
    )

    listed = client.get("/api/items?q=Floating", headers=headers).json()
    assert any(
        row["location_id"] is None and row["location_name"] is None for row in listed
    )


# --- Multi-tenant isolation -----------------------------------------------


def test_user_cannot_see_other_users_items(client, auth_token):
    """User A creates an item. User B's GET /api/items doesn't see it."""
    token_a, _ = auth_token(email="alice@test.dev", role="admin")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    cat_a = client.post(
        "/api/categories", json={"name": "AliceCat"}, headers=headers_a
    ).json()
    a_item = client.post(
        "/api/items",
        json={"sku": "ALICE-1", "name": "Alice Widget", "category_id": cat_a["id"]},
        headers=headers_a,
    ).json()
    assert a_item["owner_id"]  # sanity: response now exposes owner_id

    token_b, _ = auth_token(email="bob@test.dev", role="admin")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    bob_items = client.get("/api/items", headers=headers_b).json()
    assert not any(i["id"] == a_item["id"] for i in bob_items)


def test_user_cannot_modify_other_users_items(client, auth_token):
    """User B's PATCH / DELETE / restock / issue on User A's item all 404."""
    token_a, _ = auth_token(email="alice2@test.dev", role="admin")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    cat_a = client.post(
        "/api/categories", json={"name": "AliceCat2"}, headers=headers_a
    ).json()
    a_item = client.post(
        "/api/items",
        json={
            "sku": "ALICE-2", "name": "Alice2", "category_id": cat_a["id"],
            "quantity": 10,
        },
        headers=headers_a,
    ).json()
    a_id = a_item["id"]

    token_b, _ = auth_token(email="bob2@test.dev", role="admin")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    # GET — 404 (not 403, we don't leak existence)
    assert client.get(f"/api/items/{a_id}", headers=headers_b).status_code == 404
    # PATCH — 404
    assert client.patch(
        f"/api/items/{a_id}", json={"name": "Hijacked"}, headers=headers_b
    ).status_code == 404
    # Restock — 404
    assert client.post(
        f"/api/items/{a_id}/restock", json={"quantity": 1}, headers=headers_b
    ).status_code == 404
    # Issue — 404
    assert client.post(
        f"/api/items/{a_id}/issue", json={"quantity": 1}, headers=headers_b
    ).status_code == 404
    # DELETE — 404
    assert client.delete(f"/api/items/{a_id}", headers=headers_b).status_code == 404

    # Verify Alice's item is untouched
    a_after = client.get(f"/api/items/{a_id}", headers=headers_a).json()
    assert a_after["name"] == "Alice2"
    assert a_after["quantity"] == 10


def test_users_can_reuse_each_others_sku(client, auth_token):
    """SKU uniqueness is now per-owner (uq_items_owner_sku). User A
    and User B should both be able to have an item with sku 'COFFEE-1'."""
    token_a, _ = auth_token(email="alice3@test.dev", role="admin")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    cat_a = client.post(
        "/api/categories", json={"name": "Shared"}, headers=headers_a
    ).json()
    a_resp = client.post(
        "/api/items",
        json={"sku": "COFFEE-1", "name": "A's", "category_id": cat_a["id"]},
        headers=headers_a,
    )
    assert a_resp.status_code == 201

    token_b, _ = auth_token(email="bob3@test.dev", role="admin")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    cat_b = client.post(
        "/api/categories", json={"name": "Shared"}, headers=headers_b
    ).json()
    # Same category name "Shared" should also work (composite unique on owner+name)
    b_resp = client.post(
        "/api/items",
        json={"sku": "COFFEE-1", "name": "B's", "category_id": cat_b["id"]},
        headers=headers_b,
    )
    assert b_resp.status_code == 201
