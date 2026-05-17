"""Pagination on the workspace-list endpoints (categories, suppliers,
locations). Items + movements already had limit/offset and are
exercised by test_stock.py / test_smoke_full_flow.py."""

from __future__ import annotations


def _hdrs(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_names(client, token: str, path: str, names: list[str]) -> None:
    for name in names:
        r = client.post(path, json={"name": name}, headers=_hdrs(token))
        assert r.status_code == 201, r.text


def test_categories_limit_offset_slices_correctly(client, auth_token):
    token, _ = auth_token(role="admin")
    _seed_names(client, token, "/api/categories",
                ["A", "B", "C", "D", "E"])  # ordered alphabetically by name

    # No params → all five (backend default limit 500 returns everything).
    full = client.get("/api/categories", headers=_hdrs(token)).json()
    assert [c["name"] for c in full] == ["A", "B", "C", "D", "E"]

    # limit=2 → first slice.
    page1 = client.get("/api/categories?limit=2", headers=_hdrs(token)).json()
    assert [c["name"] for c in page1] == ["A", "B"]

    # limit=2 offset=2 → second slice.
    page2 = client.get(
        "/api/categories?limit=2&offset=2", headers=_hdrs(token)
    ).json()
    assert [c["name"] for c in page2] == ["C", "D"]

    # Final partial page.
    page3 = client.get(
        "/api/categories?limit=2&offset=4", headers=_hdrs(token)
    ).json()
    assert [c["name"] for c in page3] == ["E"]


def test_suppliers_limit_offset_slices_correctly(client, auth_token):
    token, _ = auth_token(role="admin")
    _seed_names(client, token, "/api/suppliers", ["Alpha", "Beta", "Charlie"])

    page = client.get(
        "/api/suppliers?limit=2&offset=1", headers=_hdrs(token)
    ).json()
    assert [s["name"] for s in page] == ["Beta", "Charlie"]


def test_locations_limit_offset_slices_correctly(client, auth_token):
    token, _ = auth_token(role="admin")
    _seed_names(client, token, "/api/locations",
                ["Aisle 1", "Aisle 2", "Aisle 3", "Aisle 4"])

    # Page size 2, page 2.
    page = client.get(
        "/api/locations?limit=2&offset=2", headers=_hdrs(token)
    ).json()
    assert [loc["name"] for loc in page] == ["Aisle 3", "Aisle 4"]
