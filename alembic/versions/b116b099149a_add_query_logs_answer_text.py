"""add query_logs.answer_text

Revision ID: b116b099149a
Revises: edb85f8c0627
Create Date: 2026-05-17 01:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b116b099149a"
down_revision: Union[str, Sequence[str], None] = "edb85f8c0627"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("query_logs", sa.Column("answer_text", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("query_logs", "answer_text")
