"""full-text search column + GIN index

Revision ID: a1b2c3d4e5f6
Revises: bec253a6d1fe
Create Date: 2026-09-08 06:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "bec253a6d1fe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Reserved legacy revision. Search lives in Azure AI Search (memory in tests).
    pass


def downgrade() -> None:
    pass
