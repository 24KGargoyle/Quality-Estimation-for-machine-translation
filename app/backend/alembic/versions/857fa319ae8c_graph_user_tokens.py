"""delegated graph user tokens

Revision ID: 857fa319ae8c
Revises: c7d8e9f01234
Create Date: 2026-09-18 00:00:00.000000

Adds `graph_user_tokens`, storing a delegated Microsoft Graph access/refresh
token per user for the Search Intelligence + Teams Collaboration upgrade's
"Discuss with Group" feature (finding/creating a real Teams group chat on
the user's behalf) — see docs/MICROSOFT_GRAPH_PERMISSIONS.md. No existing
table changes. Portable across SQLite and Azure SQL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '857fa319ae8c'
down_revision: Union[str, None] = 'c7d8e9f01234'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'graph_user_tokens',
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('access_token', sa.Text(), nullable=False),
        sa.Column('refresh_token', sa.Text(), nullable=True),
        sa.Column('scope', sa.String(length=500), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )


def downgrade() -> None:
    op.drop_table('graph_user_tokens')
