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
    # Generated tsvector column for keyword search over transcript chunk text.
    op.execute(
        """
        ALTER TABLE transcript_chunks
        ADD COLUMN tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('english', coalesce(text, ''))) STORED
        """
    )
    op.execute("CREATE INDEX ix_transcript_chunks_tsv ON transcript_chunks USING GIN (tsv)")

    # No DB-side vector index here: `embedding` is plain JSON and similarity is computed
    # in Python (retrieval/hybrid_search.py) so this app has no dependency on the
    # `pgvector` Postgres extension, which requires compiling from source on Windows.


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_transcript_chunks_tsv")
    op.execute("ALTER TABLE transcript_chunks DROP COLUMN IF EXISTS tsv")
