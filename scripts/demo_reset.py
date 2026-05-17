"""One-command reset for live demos.

Run this immediately before showing StockSense to anyone:

    python scripts/demo_reset.py

It:
  1. Confirms the app DB connection works.
  2. Confirms migrations are at head (warns + applies if not).
  3. Re-seeds the cafe dataset (admin user, categories, suppliers,
     locations, items, ~30 days of stock movements) via
     scripts.seed_demo. The seed is idempotent and reproducible —
     same dataset every time.
  4. Prints the demo credentials + a killer-demo prompt for
     pasting into Ask StockSense.

Does NOT touch query_logs directly — the user CASCADE in the seed's
wipe step removes them when the admin user is recreated.
"""

from __future__ import annotations

import sys

from sqlalchemy import text

from app.core.db import engine
from scripts import seed_demo

KILLER_DEMO_PROMPT = "Which items are at risk of expiring before I use them?"


def _check_db_connection() -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — surface clearly to the operator
        print(f"  X  cannot reach DB: {exc}", file=sys.stderr)
        sys.exit(1)
    print("  >  DB reachable")


def _check_migrations_at_head() -> None:
    from alembic import command
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        current = ctx.get_current_revision()
    if current != head:
        print(f"  !  migration drift: db is at {current!r}, head is {head!r}")
        print("  >  applying migrations…")
        command.upgrade(cfg, "head")
    print(f"  >  migrations at head ({head})")


def main() -> None:
    print("Resetting StockSense demo…")
    _check_db_connection()
    _check_migrations_at_head()
    print("  >  reseeding cafe dataset…")
    seed_demo.main()
    print()
    print("Demo state ready.")
    print()
    print("    Frontend:  http://localhost:3000")
    print("    Backend:   http://localhost:8001")
    print(f"    Login:     {seed_demo.ADMIN_EMAIL} / {seed_demo.ADMIN_PASSWORD}")
    print()
    print("Killer demo prompt for Ask StockSense:")
    print(f"    \"{KILLER_DEMO_PROMPT}\"")


if __name__ == "__main__":
    main()
