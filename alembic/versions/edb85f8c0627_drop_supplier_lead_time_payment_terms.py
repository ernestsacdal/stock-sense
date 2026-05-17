"""drop unused supplier.lead_time_days + payment_terms

Revision ID: edb85f8c0627
Revises: ae1737cdf88d
Create Date: 2026-05-17 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "edb85f8c0627"
down_revision: Union[str, Sequence[str], None] = "ae1737cdf88d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Both columns were displayed + editable but never read by any
    # business logic (insights reorder math hardcodes DEFAULT_LEAD_TIME,
    # nothing reads payment_terms at all). Drop them.
    op.drop_column("suppliers", "lead_time_days")
    op.drop_column("suppliers", "payment_terms")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("suppliers", sa.Column("lead_time_days", sa.Integer(), nullable=True))
    op.add_column("suppliers", sa.Column("payment_terms", sa.String(length=120), nullable=True))
