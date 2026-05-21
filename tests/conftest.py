"""Pytest fixtures for the StockSense backend test suite.

Strategy:
- Force a separate Postgres database (stocksense_test) BEFORE any app
  module imports settings. The dev DB (stocksense_dev) is never touched.
- Once per session: run alembic upgrade head so the test DB matches
  the migration head.
- Each test that needs a clean DB: truncate every inventory + audit
  table (CASCADE) at the start. Tests are isolated, ordering doesn't
  matter, and we avoid transaction-rollback gymnastics that fight with
  the routers' own session.commit() calls.
"""

from __future__ import annotations

import os

# These two MUST be set before importing anything from app/.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://stocksense_app:dev_app_password@localhost:5432/stocksense_test",
)
os.environ.setdefault("JWT_SECRET", "test_jwt_secret_not_for_production")
os.environ.setdefault("BACKEND_CORS_ORIGINS", "http://localhost:3000")
# Force stub mode for the LLM regardless of what's in .env so tests
# stay reproducible (no network call, no credit burn, no test flakes
# from upstream rate limits). The stub path is end-to-end identical
# to the real path — just deterministic.
os.environ["OPENROUTER_API_KEY"] = ""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import engine
from app.main import app

_INVENTORY_TABLES = (
    "stock_movements",
    "items",
    "suppliers",
    "locations",
    "categories",
    "query_logs",
    "users",
)


@pytest.fixture(scope="session", autouse=True)
def _migrate_test_db():
    """Apply migrations to the test DB once per session."""
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _wipe_db():
    """Truncate every inventory + audit table before each test."""
    with engine.begin() as conn:
        conn.execute(
            text(
                f"TRUNCATE TABLE {', '.join(_INVENTORY_TABLES)} RESTART IDENTITY CASCADE"
            )
        )
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_token(client: TestClient):
    """Register a user, return (token, user_dict)."""

    def _register_and_login(
        email: str = "test@stocksense.dev",
        password: str = "testpass123",
        role: str | None = None,  # noqa: ARG001 — kept for back-compat with
        # existing callers that pass role="admin". RBAC was removed when the
        # multi-tenant refactor made every user the sole owner of their own
        # workspace (migration 95238bae6720). Param is a no-op; remove this
        # whole kwarg + the unused-arg suppression once callers are updated.
    ) -> tuple[str, dict]:
        client.post(
            "/api/auth/register",
            json={"email": email, "password": password},
        )
        login = client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
        token = login.json()["access_token"]
        me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        return token, me.json()

    return _register_and_login
