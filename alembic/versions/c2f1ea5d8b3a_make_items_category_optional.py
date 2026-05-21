"""make items.category_id optional + SET NULL on category delete

Categories no longer block on having items pointing at them — small
businesses regularly want to delete or reorganise categories without
also disturbing the items themselves. With this migration:

  * items.category_id is nullable (an item can be uncategorised)
  * the FK is ON DELETE SET NULL — deleting a category clears
    category_id on the items that referenced it rather than RESTRICTing.

The 409 "category is in use by items" branch in the categories
router becomes defensive dead code; left in place in case future
constraints (other than items.category_id) get added.

Revision ID: c2f1ea5d8b3a
Revises: 95238bae6720
Create Date: 2026-05-21 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c2f1ea5d8b3a"
down_revision: Union[str, Sequence[str], None] = "95238bae6720"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Drop NOT NULL on the column.
    op.alter_column("items", "category_id", nullable=True)
    # 2. Recreate the FK so it SET NULLs instead of RESTRICTing. Postgres
    #    won't let you alter an FK's ON DELETE behaviour in place — drop
    #    and recreate.
    op.drop_constraint("items_category_id_fkey", "items", type_="foreignkey")
    op.create_foreign_key(
        "items_category_id_fkey",
        "items",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema.

    Best-effort reverse. If any items have category_id IS NULL when
    downgrading you'll need to backfill them first; this script does
    not invent a default category.
    """
    op.drop_constraint("items_category_id_fkey", "items", type_="foreignkey")
    op.create_foreign_key(
        "items_category_id_fkey",
        "items",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.alter_column("items", "category_id", nullable=False)
