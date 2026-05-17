"""add items.notes nullable text column

Revision ID: ae1737cdf88d
Revises: 23dc1630696e
Create Date: 2026-05-16 23:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ae1737cdf88d"
down_revision: Union[str, Sequence[str], None] = "23dc1630696e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("items", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("items", "notes")
