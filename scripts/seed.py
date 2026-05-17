"""Empty-state seed for the StockSense local dev database.

Wipes every inventory table and creates just the admin user — the
UI handles the empty state on every page. Useful when you want a
clean slate for testing the empty-state UX or when you'd rather
build your inventory by clicking through the forms yourself.

For a populated demo dataset (10 items, mixed stock states,
movement history), use scripts/seed_demo.py instead.

Idempotent: re-runnable any time. Always recreates the admin user
(admin@admin.com.au / dev_admin_password) with a default
business_name of "Demo Inventory".
"""

from __future__ import annotations

from sqlalchemy import delete

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.category import Category
from app.models.item import Item
from app.models.location import Location
from app.models.movement import StockMovement
from app.models.query_log import QueryLog
from app.models.supplier import Supplier
from app.models.user import User, UserRole

ADMIN_EMAIL = "admin@admin.com.au"
ADMIN_PASSWORD = "dev_admin_password"
ADMIN_BUSINESS_NAME = "Demo Inventory"


def main() -> None:
    with SessionLocal() as session:
        # Wipe in reverse-FK order. Cascade on user_id covers query_logs.
        session.execute(delete(StockMovement))
        session.execute(delete(Item))
        session.execute(delete(Supplier))
        session.execute(delete(Location))
        session.execute(delete(Category))
        session.execute(delete(QueryLog))
        session.execute(delete(User))
        session.commit()

        admin = User(
            email=ADMIN_EMAIL,
            password_hash=hash_password(ADMIN_PASSWORD),
            role=UserRole.admin,
            business_name=ADMIN_BUSINESS_NAME,
        )
        session.add(admin)
        session.commit()

        print(f"Seeded admin: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        print(f"Business name: {ADMIN_BUSINESS_NAME}")
        print("Inventory tables empty — populate via the UI.")


if __name__ == "__main__":
    main()
