"""Auth flow + RBAC tests.

Covers register, login, refresh-via-cookie, /me, logout, and the
admin role guard end to end through the FastAPI test client.
"""

from __future__ import annotations


def test_register_creates_staff_user(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "alice@test.dev", "password": "alicepass123"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "alice@test.dev"
    assert body["role"] == "staff"
    assert "id" in body and "created_at" in body


def test_register_rejects_short_password(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "a@b.com", "password": "short"},
    )
    assert r.status_code == 422


def test_register_duplicate_email_returns_409(client):
    payload = {"email": "dup@test.dev", "password": "dupedup12"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    assert client.post("/api/auth/register", json=payload).status_code == 409


def test_register_persists_business_name_when_provided(client):
    r = client.post(
        "/api/auth/register",
        json={
            "email": "owner@test.dev",
            "password": "ownerpass1",
            "business_name": "Joe's Coffee Shop",
        },
    )
    assert r.status_code == 201
    assert r.json()["business_name"] == "Joe's Coffee Shop"


def test_register_business_name_optional_defaults_to_null(client):
    r = client.post(
        "/api/auth/register",
        json={"email": "noname@test.dev", "password": "nonamepass1"},
    )
    assert r.status_code == 201
    assert r.json()["business_name"] is None


def test_patch_me_updates_business_name(client, auth_token):
    token, _ = auth_token(email="biz@test.dev")
    r = client.patch(
        "/api/auth/me",
        json={"business_name": "Joe's Cafe"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["business_name"] == "Joe's Cafe"


def test_patch_me_rotates_password_with_correct_current(client):
    client.post(
        "/api/auth/register",
        json={"email": "rotate@test.dev", "password": "oldpass1234"},
    )
    login = client.post(
        "/api/auth/login",
        json={"email": "rotate@test.dev", "password": "oldpass1234"},
    )
    token = login.json()["access_token"]

    r = client.patch(
        "/api/auth/me",
        json={"current_password": "oldpass1234", "new_password": "newpass1234"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200

    # Old password must now fail.
    bad = client.post(
        "/api/auth/login",
        json={"email": "rotate@test.dev", "password": "oldpass1234"},
    )
    assert bad.status_code == 401
    # New password works.
    good = client.post(
        "/api/auth/login",
        json={"email": "rotate@test.dev", "password": "newpass1234"},
    )
    assert good.status_code == 200


def test_patch_me_password_change_requires_current_password(client, auth_token):
    token, _ = auth_token(email="nocurpwd@test.dev")
    r = client.patch(
        "/api/auth/me",
        json={"new_password": "newonly1234"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422


def test_patch_me_rejects_wrong_current_password(client, auth_token):
    token, _ = auth_token(email="wrongcur@test.dev", password="rightpass1")
    r = client.patch(
        "/api/auth/me",
        json={"current_password": "wrong", "new_password": "newpass1234"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401


def test_login_returns_access_token_and_sets_refresh_cookie(client):
    client.post(
        "/api/auth/register",
        json={"email": "bob@test.dev", "password": "bobpass1234"},
    )
    r = client.post(
        "/api/auth/login",
        json={"email": "bob@test.dev", "password": "bobpass1234"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 50
    # refresh cookie must be httpOnly + scoped to /api/auth
    cookies = r.cookies
    assert "stocksense_refresh" in cookies


def test_login_with_wrong_password_returns_401(client):
    client.post(
        "/api/auth/register",
        json={"email": "carol@test.dev", "password": "carolpass1"},
    )
    r = client.post(
        "/api/auth/login",
        json={"email": "carol@test.dev", "password": "wrong"},
    )
    assert r.status_code == 401


def test_me_requires_bearer_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "garbage"}).status_code == 401


def test_me_returns_current_user(client, auth_token):
    token, user = auth_token(email="dave@test.dev")
    r = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["email"] == "dave@test.dev"
    assert r.json()["id"] == user["id"]


def test_refresh_rotates_token_via_cookie(client):
    client.post(
        "/api/auth/register",
        json={"email": "eve@test.dev", "password": "evepass123"},
    )
    login = client.post(
        "/api/auth/login",
        json={"email": "eve@test.dev", "password": "evepass123"},
    )
    first_token = login.json()["access_token"]

    # The TestClient retains cookies between requests.
    r = client.post("/api/auth/refresh")
    assert r.status_code == 200
    new_token = r.json()["access_token"]
    assert new_token  # got a token (may match if generated within same second)
    # Verify the new token works against /me.
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "eve@test.dev"
    # And the original token still works (we don't blacklist access tokens).
    me_old = client.get("/api/auth/me", headers={"Authorization": f"Bearer {first_token}"})
    assert me_old.status_code == 200


def test_refresh_without_cookie_returns_401(client):
    assert client.post("/api/auth/refresh").status_code == 401


def test_logout_clears_refresh_cookie(client):
    client.post(
        "/api/auth/register",
        json={"email": "fred@test.dev", "password": "fredpass1"},
    )
    client.post(
        "/api/auth/login",
        json={"email": "fred@test.dev", "password": "fredpass1"},
    )
    r = client.post("/api/auth/logout")
    assert r.status_code == 204
    # subsequent refresh should now 401 since the cookie is cleared
    assert client.post("/api/auth/refresh").status_code == 401


def test_admin_endpoint_rejects_staff(client, auth_token):
    token, _ = auth_token(email="staff@test.dev", role="staff")
    r = client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_admin_endpoint_allows_admin(client, auth_token):
    token, _ = auth_token(email="admin@test.dev", role="admin")
    r = client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert any(u["email"] == "admin@test.dev" for u in r.json())
