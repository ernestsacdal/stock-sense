"""Rich demo seed for clicking through the whole app.

Wipes every inventory table and rebuilds a small-business cafe with
realistic state across every UI surface: items at every stock status
(healthy / low / critical), perishable items with near + far expiry,
items with notes, varied unit costs, and ~30 days of stock movements
so the dashboard chart and activity feed have shape and the Ask AI
has data to talk about.

Run from backend/:
    python -m scripts.seed_demo

Idempotent: re-run to reset to the same state.

For an empty admin-only seed (clean-slate UX testing), use seed.py.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, text

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.category import Category
from app.models.item import Item
from app.models.location import Location
from app.models.movement import MovementType, StockMovement
from app.models.query_log import QueryLog
from app.models.supplier import Supplier
from app.models.user import User, UserRole


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADMIN_EMAIL = "joe@coffee.dev"
ADMIN_PASSWORD = "joepass123"
ADMIN_BUSINESS_NAME = "Joe's Coffee Shop"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    with SessionLocal() as session:
        # 1) Wipe everything (reverse-FK order; user cascade covers query_logs).
        session.execute(delete(StockMovement))
        session.execute(delete(Item))
        session.execute(delete(Supplier))
        session.execute(delete(Location))
        session.execute(delete(Category))
        session.execute(delete(QueryLog))
        session.execute(delete(User))
        session.commit()

        # 2) Admin user (sole user — multi-user is out of scope).
        admin = User(
            email=ADMIN_EMAIL,
            password_hash=hash_password(ADMIN_PASSWORD),
            role=UserRole.admin,
            business_name=ADMIN_BUSINESS_NAME,
        )
        session.add(admin)
        session.flush()

        # 3) Categories — all owned by the admin (this is admin's workspace).
        cats = {
            name: Category(owner_id=admin.id, name=name)
            for name in ("Beans", "Milk", "Sweeteners", "Cleaning")
        }
        for c in cats.values():
            session.add(c)
        session.flush()

        # 4) Suppliers.
        sups = {
            "Bean Supply Co": Supplier(
                owner_id=admin.id,
                name="Bean Supply Co",
                contact="rep@beansupply.dev",
                notes="Rep is Mark; orders Fridays only.",
            ),
            "Daily Dairy": Supplier(
                owner_id=admin.id,
                name="Daily Dairy",
                contact="orders@dailydairy.dev",
            ),
            "ChemKing": Supplier(
                owner_id=admin.id,
                name="ChemKing",
                contact="sales@chemking.dev",
            ),
        }
        for s in sups.values():
            session.add(s)
        session.flush()

        # 5) Locations.
        locs = {
            "Front Bar": Location(owner_id=admin.id, name="Front Bar", type="storage"),
            "Storeroom": Location(owner_id=admin.id, name="Storeroom", type="storage"),
        }
        for loc in locs.values():
            session.add(loc)
        session.flush()

        today = date.today()

        # 6) Items — final quantity values match what the seeded movements
        #    sum to (computed in step 7 below).
        items_data = [
            # name, sku, qty, unit_cost, threshold, expiry_days, category, supplier, location, notes
            ("Espresso Beans 1kg", "BEAN-ESP-1K", 12, "18.50", 5,  60, "Beans",      "Bean Supply Co", "Storeroom",
             "Order Friday only — rep is Mark."),
            ("Decaf Beans 1kg",    "BEAN-DEC-1K", 4,  "22.00", 5,  90, "Beans",      "Bean Supply Co", "Storeroom", None),
            ("Whole Milk 2L",      "MILK-WHL-2L", 8,  "3.50",  6,   5, "Milk",       "Daily Dairy",    "Front Bar", None),
            ("Oat Milk 1L",        "MILK-OAT-1L", 12, "4.20",  4,  20, "Milk",       "Daily Dairy",    "Front Bar", None),
            ("Soy Milk 1L",        "MILK-SOY-1L", 0,  "3.80",  3,  25, "Milk",       "Daily Dairy",    "Front Bar",
             "Customer favourite — reorder ASAP."),
            ("Brown Sugar 5kg",    "SUG-BRN-5K",  3,  "12.50", 2, None, "Sweeteners","Bean Supply Co", "Storeroom", None),
            ("Honey 1L",           "SWT-HON-1L",  2,  "18.00", 1, 180, "Sweeteners","Bean Supply Co", "Storeroom", None),
            ("Dish Soap 5L",       "CLN-DSH-5L",  5,  "22.00", None, None, "Cleaning","ChemKing",      "Storeroom", None),
            ("Sanitizer Spray 1L", "CLN-SAN-1L",  8,  "8.50",  None, 30, "Cleaning", "ChemKing",      "Storeroom",
             "Use within 30 days of opening."),
            ("Coffee Filters 100ct","BEAN-FLT-100",25,"6.00",  10, None, "Beans",    "Bean Supply Co", "Storeroom", None),
        ]

        items_by_sku: dict[str, Item] = {}
        for (name, sku, qty, cost, threshold, exp_days,
             cat_name, sup_name, loc_name, notes) in items_data:
            item = Item(
                owner_id=admin.id,
                sku=sku,
                name=name,
                category_id=cats[cat_name].id,
                supplier_id=sups[sup_name].id,
                location_id=locs[loc_name].id,
                reorder_threshold=threshold,
                quantity=qty,
                unit_cost=Decimal(cost),
                expiry_date=(today + timedelta(days=exp_days)) if exp_days is not None else None,
                notes=notes,
            )
            session.add(item)
            items_by_sku[sku] = item
        session.flush()

        # 7) Historical stock movements. The math sums to the items'
        #    quantity values above (verified per-item). Raw SQL because
        #    we need explicit created_at; the API only stamps "now".
        now = datetime.now(timezone.utc)

        def days_ago(d: int) -> datetime:
            # Sprinkle hours so multiple movements per day don't collide.
            return now - timedelta(days=d, hours=d % 8, minutes=(d * 13) % 60)

        movements: list[tuple[str, str, int, int, str | None]] = [
            # (sku, type, delta, days_ago, notes)
            # --- Espresso Beans (final 12) ---
            ("BEAN-ESP-1K", "added",    10, 28, None),
            ("BEAN-ESP-1K", "received", 10, 14, None),
            ("BEAN-ESP-1K", "issued",   -5,  7, None),
            ("BEAN-ESP-1K", "issued",   -3,  3, None),

            # --- Decaf Beans (final 4) ---
            ("BEAN-DEC-1K", "added", 6, 25, None),
            ("BEAN-DEC-1K", "issued", -2, 10, None),

            # --- Whole Milk 2L (final 8) ---
            ("MILK-WHL-2L", "added",   12, 28, None),
            ("MILK-WHL-2L", "issued",  -2, 20, None),
            ("MILK-WHL-2L", "received", 6, 14, None),
            ("MILK-WHL-2L", "issued",  -2, 10, None),
            ("MILK-WHL-2L", "issued",  -2,  7, None),
            ("MILK-WHL-2L", "disposed",-1,  5, "Spoiled."),
            ("MILK-WHL-2L", "issued",  -3,  3, None),

            # --- Oat Milk (final 12) ---
            ("MILK-OAT-1L", "added",   12, 28, None),
            ("MILK-OAT-1L", "issued",  -2, 14, None),
            ("MILK-OAT-1L", "received", 5,  7, None),
            ("MILK-OAT-1L", "issued",  -3,  3, None),

            # --- Soy Milk (final 0 — critical) ---
            ("MILK-SOY-1L", "added",   5, 25, None),
            ("MILK-SOY-1L", "issued", -2, 14, None),
            ("MILK-SOY-1L", "issued", -2,  7, None),
            ("MILK-SOY-1L", "issued", -1,  2, None),

            # --- Brown Sugar (final 3) ---
            ("SUG-BRN-5K", "added",     5, 28, None),
            ("SUG-BRN-5K", "issued",   -1, 10, None),
            ("SUG-BRN-5K", "adjusted", -1,  7, "Counting error."),

            # --- Honey (final 2) ---
            ("SWT-HON-1L", "added",  3, 20, None),
            ("SWT-HON-1L", "issued", -1, 8, None),

            # --- Dish Soap (final 5) ---
            ("CLN-DSH-5L", "added", 5, 28, None),

            # --- Sanitizer Spray (final 8) ---
            ("CLN-SAN-1L", "added",  10, 25, None),
            ("CLN-SAN-1L", "issued", -2, 12, None),

            # --- Coffee Filters (final 25) ---
            ("BEAN-FLT-100", "added",   20, 28, None),
            ("BEAN-FLT-100", "issued",  -5, 21, None),
            ("BEAN-FLT-100", "received",15, 14, None),
            ("BEAN-FLT-100", "issued",  -5,  7, None),
        ]

        # Self-check: each item's delta sum must match the item.quantity
        # we wrote. Catches data-entry slips early.
        sums: dict[str, int] = {}
        for sku, _, delta, _, _ in movements:
            sums[sku] = sums.get(sku, 0) + delta
        for sku, item in items_by_sku.items():
            assert sums.get(sku, 0) == item.quantity, (
                f"movement sum {sums.get(sku, 0)} != item.quantity {item.quantity} for {sku}"
            )

        for sku, mtype, delta, d_ago, notes in movements:
            session.execute(
                text(
                    """
                    INSERT INTO stock_movements
                      (owner_id, item_id, type, quantity_delta, user_id, notes, created_at)
                    VALUES
                      (:owner_id, :item_id, :type, :delta, :user_id, :notes, :when)
                    """
                ),
                {
                    "owner_id": admin.id,
                    "item_id": items_by_sku[sku].id,
                    "type": MovementType(mtype).value,
                    "delta": delta,
                    "user_id": admin.id,
                    "notes": notes,
                    "when": days_ago(d_ago),
                },
            )

        session.commit()

        # 8) Friendly summary.
        print("Seeded demo dataset — Joe's Coffee Shop")
        print(f"  > admin:      {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        print(f"  > categories: {len(cats)}")
        print(f"  > suppliers:  {len(sups)}")
        print(f"  > locations:  {len(locs)}")
        print(f"  > items:      {len(items_by_sku)}")
        print(f"  > movements:  {len(movements)} (spread across the last 30 days)")
        print()
        print("Killer demo prompts for Ask StockSense:")
        print('  "What\'s running low?"')
        print('  "Where is most of my money parked?"')
        print('  "Which items are at risk of expiring before I use them?"')


if __name__ == "__main__":
    main()
