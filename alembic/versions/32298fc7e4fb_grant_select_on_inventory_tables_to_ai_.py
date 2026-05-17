"""grant select on inventory tables to ai read-only role

Revision ID: 32298fc7e4fb
Revises: 15072f9d5415
Create Date: 2026-05-15 12:19:47.103048

The AI natural-language query feature ("Ask StockSense") executes
generated SQL against a dedicated read-only Postgres role. This
migration creates that role's table-level access:

  - USAGE on schema public so it can resolve table names.
  - SELECT on every existing inventory table.
  - Default privileges so future tables created by stocksense_app
    are also automatically readable.

The role itself (stocksense_ai_ro) is created out-of-band as part of
the project's one-time DB setup (documented in backend/README.md),
because role creation requires superuser privileges.

If the role does not exist when this migration runs, it is a no-op
(IF EXISTS-style guard via DO block) — useful in fresh environments
where the developer hasn't yet run the role-create SQL.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "32298fc7e4fb"
down_revision: Union[str, Sequence[str], None] = "15072f9d5415"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_AI_RO_ROLE = "stocksense_ai_ro"


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_AI_RO_ROLE}') THEN
            EXECUTE 'GRANT USAGE ON SCHEMA public TO {_AI_RO_ROLE}';
            EXECUTE 'GRANT SELECT ON ALL TABLES IN SCHEMA public TO {_AI_RO_ROLE}';
            EXECUTE 'GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO {_AI_RO_ROLE}';
            EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {_AI_RO_ROLE}';
            EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO {_AI_RO_ROLE}';
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_AI_RO_ROLE}') THEN
            EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON TABLES FROM {_AI_RO_ROLE}';
            EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE SELECT ON SEQUENCES FROM {_AI_RO_ROLE}';
            EXECUTE 'REVOKE SELECT ON ALL TABLES IN SCHEMA public FROM {_AI_RO_ROLE}';
            EXECUTE 'REVOKE SELECT ON ALL SEQUENCES IN SCHEMA public FROM {_AI_RO_ROLE}';
            EXECUTE 'REVOKE USAGE ON SCHEMA public FROM {_AI_RO_ROLE}';
          END IF;
        END $$;
        """
    )
