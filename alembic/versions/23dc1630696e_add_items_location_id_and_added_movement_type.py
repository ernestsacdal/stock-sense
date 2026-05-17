"""add items.location_id and 'added' movement_type enum value

Revision ID: 23dc1630696e
Revises: 0038f210c3c3
Create Date: 2026-05-16 23:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "23dc1630696e"
down_revision: Union[str, Sequence[str], None] = "0038f210c3c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Items: optional location FK (mirrors supplier_id).
    op.add_column("items", sa.Column("location_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("items_location_id_fkey"),
        "items", "locations", ["location_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(op.f("ix_items_location_id"), "items", ["location_id"], unique=False)

    # Movement type: add 'added' for "logged at item creation with initial qty > 0".
    # Postgres requires ALTER TYPE ... ADD VALUE for native enums. Empty seed
    # means no rows reference the enum yet — this is safe.
    # IF NOT EXISTS makes the migration idempotent if it's ever partially run.
    # ADD VALUE must be outside a transaction; use the autocommit block.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE movement_type ADD VALUE IF NOT EXISTS 'added' BEFORE 'received'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_items_location_id"), table_name="items")
    op.drop_constraint(op.f("items_location_id_fkey"), "items", type_="foreignkey")
    op.drop_column("items", "location_id")
    # Note: Postgres doesn't support removing a value from an enum without
    # recreating the type. Since the empty-seed convention means downgrades
    # are only ever run in development, we leave the 'added' value in place.
