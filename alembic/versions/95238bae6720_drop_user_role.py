"""drop users.role and the user_role enum

After the multi-tenant refactor (041c5caf10bf), every user owns their
own workspace via owner_id + Postgres RLS. RBAC roles (admin / manager
/ staff) no longer carry meaning — and the old _WRITE = require_role
guards on the write endpoints were silently blocking every fresh
signup from creating anything (defaulted to staff, staff couldn't
write). Drop the column + enum entirely; the route-level guards
disappear in the same commit.

Revision ID: 95238bae6720
Revises: 041c5caf10bf
Create Date: 2026-05-19 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "95238bae6720"
down_revision: Union[str, Sequence[str], None] = "041c5caf10bf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("users", "role")
    # Drop the Postgres enum type that backed the column. Safe because
    # the column above is the only consumer of this type.
    op.execute("DROP TYPE IF EXISTS user_role")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "CREATE TYPE user_role AS ENUM ('admin', 'manager', 'staff')"
    )
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.Enum("admin", "manager", "staff", name="user_role"),
            nullable=False,
            server_default="staff",
        ),
    )
