"""add query_logs table for ask stocksense audit

Revision ID: 53fdb8094134
Revises: 32298fc7e4fb
Create Date: 2026-05-15 13:06:00.467353

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '53fdb8094134'
down_revision: Union[str, Sequence[str], None] = '32298fc7e4fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('query_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('generated_sql', sa.Text(), nullable=True),
    sa.Column('status', sa.Enum('ok', 'llm_error', 'safety_rejected', 'exec_error', 'timeout', name='query_status'), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('row_count', sa.Integer(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_query_logs_created_at'), 'query_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_query_logs_user_id'), 'query_logs', ['user_id'], unique=False)

    # The audit log must not be visible to the AI role — it contains every
    # past question + generated SQL. Default privileges grant SELECT to
    # stocksense_ai_ro on every new table; revoke explicitly for query_logs.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'stocksense_ai_ro') THEN
            EXECUTE 'REVOKE ALL ON query_logs FROM stocksense_ai_ro';
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_query_logs_user_id'), table_name='query_logs')
    op.drop_index(op.f('ix_query_logs_created_at'), table_name='query_logs')
    op.drop_table('query_logs')
    sa.Enum(name='query_status').drop(op.get_bind(), checkfirst=True)
