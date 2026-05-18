"""per-user workspaces — add owner_id to inventory tables + RLS for ai_ro

Adds owner_id (FK to users.id) to items / categories / suppliers /
locations / stock_movements. Backfills existing rows to the first
admin user so the seeded demo data stays intact. Enables row-level
security policies so the AI read-only role (stocksense_ai_ro) can
only see rows for the current request's user — even if the LLM
generates a `SELECT * FROM items`.

Revision ID: 041c5caf10bf
Revises: b116b099149a
Create Date: 2026-05-18 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "041c5caf10bf"
down_revision: Union[str, Sequence[str], None] = "b116b099149a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables that gain owner_id and RLS. query_logs already has user_id
# (audit owner is implicit), users is the owner — neither needs the
# treatment.
_TABLES = ("items", "categories", "suppliers", "locations", "stock_movements")


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Add owner_id nullable so the backfill can run.
    for table in _TABLES:
        op.add_column(table, sa.Column("owner_id", sa.Integer(), nullable=True))

    # 2. Backfill to the first admin (or first user if no admin yet).
    #    This keeps the seeded demo data attached to joe@coffee.dev on
    #    existing deployments. Fresh DBs have no rows to backfill —
    #    the UPDATE is a no-op.
    op.execute(
        """
        WITH fallback AS (
            SELECT COALESCE(
                (SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1),
                (SELECT id FROM users ORDER BY id LIMIT 1)
            ) AS uid
        )
        UPDATE items SET owner_id = (SELECT uid FROM fallback)
        WHERE owner_id IS NULL;
        """
    )
    for table in ("categories", "suppliers", "locations", "stock_movements"):
        op.execute(
            f"""
            UPDATE {table} SET owner_id = (
                SELECT COALESCE(
                    (SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1),
                    (SELECT id FROM users ORDER BY id LIMIT 1)
                )
            )
            WHERE owner_id IS NULL;
            """
        )

    # 3. Lock owner_id NOT NULL + FK + index. If any table is non-empty
    #    and step 2 didn't backfill (e.g. zero users), the NOT NULL
    #    constraint will fail — surface that explicitly rather than
    #    silently leaving nullable columns.
    for table in _TABLES:
        op.alter_column(table, "owner_id", nullable=False)
        op.create_foreign_key(
            op.f(f"{table}_owner_id_fkey"),
            table, "users", ["owner_id"], ["id"], ondelete="CASCADE",
        )
        op.create_index(op.f(f"ix_{table}_owner_id"), table, ["owner_id"])

    # 3b. Swap global uniqueness → per-owner uniqueness for the three
    #     name/code columns that gate inserts. Without this, User B
    #     couldn't create a category named "Beans" if User A already
    #     had one — which defeats the per-user-workspace point.
    #     locations.name has no unique constraint today; leave as-is.
    #
    #     categories.name + items.sku used `unique=True, index=True`
    #     → that's a UNIQUE INDEX (no separate constraint). Drop the
    #     unique index, create a plain index, add composite unique.
    op.drop_index("ix_categories_name", table_name="categories")
    op.create_index("ix_categories_name", "categories", ["name"])
    op.create_unique_constraint(
        "uq_categories_owner_name", "categories", ["owner_id", "name"]
    )

    op.drop_index("ix_items_sku", table_name="items")
    op.create_index("ix_items_sku", "items", ["sku"])
    op.create_unique_constraint(
        "uq_items_owner_sku", "items", ["owner_id", "sku"]
    )

    # suppliers.name used `unique=True` (no index=True) → that's a
    # named UNIQUE CONSTRAINT (suppliers_name_key) with an auto-
    # generated backing index. Drop the constraint, add composite.
    op.drop_constraint("suppliers_name_key", "suppliers", type_="unique")
    op.create_unique_constraint(
        "uq_suppliers_owner_name", "suppliers", ["owner_id", "name"]
    )

    # 4. Row-level security for the AI read-only role.
    #    The app role (stocksense_app, which owns the tables) bypasses
    #    RLS automatically. The AI role does NOT — it only sees rows
    #    where owner_id matches the session-set app.current_user_id.
    #    The executor sets that before every query.
    #    NULLIF + COALESCE pattern: if the setting isn't set, the
    #    policy returns no rows (safer default than "see everything").
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table}_owner_isolation ON {table}
                FOR SELECT TO stocksense_ai_ro
                USING (
                    owner_id = NULLIF(
                        current_setting('app.current_user_id', true),
                        ''
                    )::int
                );
            """
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Reverse the unique-constraint swaps first (need owner_id while
    # we still have it, since the composite uniques reference it).
    op.drop_constraint("uq_suppliers_owner_name", "suppliers", type_="unique")
    op.create_unique_constraint("suppliers_name_key", "suppliers", ["name"])

    op.drop_constraint("uq_items_owner_sku", "items", type_="unique")
    op.drop_index("ix_items_sku", table_name="items")
    op.create_index("ix_items_sku", "items", ["sku"], unique=True)

    op.drop_constraint("uq_categories_owner_name", "categories", type_="unique")
    op.drop_index("ix_categories_name", table_name="categories")
    op.create_index("ix_categories_name", "categories", ["name"], unique=True)

    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_owner_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
        op.drop_index(op.f(f"ix_{table}_owner_id"), table_name=table)
        op.drop_constraint(op.f(f"{table}_owner_id_fkey"), table, type_="foreignkey")
        op.drop_column(table, "owner_id")
