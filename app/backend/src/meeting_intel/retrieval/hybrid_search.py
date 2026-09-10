"""Hybrid (vector + keyword) retrieval with mandatory metadata filtering.

`meeting_ids` is always required and always enforced server-side — callers
(the Retrieval Agent) decide which meeting(s) are in scope; this module never
searches beyond the ids it is given. Cross-meeting search is therefore only
possible when the caller explicitly passes more than one meeting id, which
only happens when `agents.meeting_router` detects an explicit cross-meeting
request (see docs/RAG_ARCHITECTURE.md).

Vector similarity is computed in Python (numpy dot product over normalized
embeddings, i.e. cosine similarity) rather than in the database — this app
intentionally has no dependency on the `pgvector` Postgres extension, which
has no plain installer on Windows and would otherwise force Docker/WSL2 on
Windows contributors. See docs/RAG_ARCHITECTURE.md for the tradeoff this
makes against a DB-side ANN index (fine at meeting-transcript scale — at
most a few hundred chunks per meeting/search scope).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.config import get_settings
from meeting_intel.db.models import TranscriptChunk
from meeting_intel.embeddings.embedder import embed_query

settings = get_settings()


@dataclass
class RetrievedChunk:
    chunk: TranscriptChunk
    score: float
    vector_rank: int | None
    keyword_rank: int | None


def _rrf(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


async def hybrid_search(
    db: AsyncSession,
    *,
    meeting_ids: list[str],
    query: str,
    speaker: str | None = None,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    if not meeting_ids:
        return []
    top_k = top_k or settings.retrieval_top_k
    query_vector = np.array(embed_query(query), dtype=np.float32)

    candidates_stmt = select(TranscriptChunk).where(TranscriptChunk.meeting_id.in_(meeting_ids))
    keyword_stmt = (
        select(TranscriptChunk)
        .where(TranscriptChunk.meeting_id.in_(meeting_ids))
        .where(text("tsv @@ plainto_tsquery('english', :kw)"))
        .params(kw=query)
    )
    if speaker:
        candidates_stmt = candidates_stmt.where(func.lower(TranscriptChunk.speaker) == speaker.lower())
        keyword_stmt = keyword_stmt.where(func.lower(TranscriptChunk.speaker) == speaker.lower())

    keyword_stmt = keyword_stmt.order_by(
        text("ts_rank_cd(tsv, plainto_tsquery('english', :kw)) DESC")
    ).params(kw=query).limit(top_k * 3)

    candidates = (await db.execute(candidates_stmt)).scalars().all()
    keyword_rows = (await db.execute(keyword_stmt)).scalars().all()

    embedded = [c for c in candidates if c.embedding]
    if embedded:
        matrix = np.array([c.embedding for c in embedded], dtype=np.float32)
        similarities = matrix @ query_vector
        order = np.argsort(-similarities)[: top_k * 3]
        vector_rows = [embedded[i] for i in order]
    else:
        vector_rows = []

    fused: dict[str, RetrievedChunk] = {}
    for rank, chunk in enumerate(vector_rows, start=1):
        fused[chunk.id] = RetrievedChunk(chunk=chunk, score=_rrf(rank), vector_rank=rank, keyword_rank=None)
    for rank, chunk in enumerate(keyword_rows, start=1):
        if chunk.id in fused:
            fused[chunk.id].score += _rrf(rank)
            fused[chunk.id].keyword_rank = rank
        else:
            fused[chunk.id] = RetrievedChunk(chunk=chunk, score=_rrf(rank), vector_rank=None, keyword_rank=rank)

    ranked = sorted(fused.values(), key=lambda r: r.score, reverse=True)
    return ranked[:top_k]
