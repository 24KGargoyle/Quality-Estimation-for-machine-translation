"""Hybrid (vector + keyword) retrieval with mandatory metadata filtering.

`meeting_ids` is always required and always enforced server-side — callers
(the Retrieval Agent) decide which meeting(s) are in scope; this module never
searches beyond the ids it is given. Cross-meeting search is therefore only
possible when the caller explicitly passes more than one meeting id, which
only happens when `agents.meeting_router` detects an explicit cross-meeting
request (see docs/RAG_ARCHITECTURE.md).
"""
from __future__ import annotations

from dataclasses import dataclass

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
    query_vector = embed_query(query)

    vector_stmt = select(TranscriptChunk).where(TranscriptChunk.meeting_id.in_(meeting_ids))
    keyword_stmt = (
        select(TranscriptChunk)
        .where(TranscriptChunk.meeting_id.in_(meeting_ids))
        .where(text("tsv @@ plainto_tsquery('english', :kw)"))
        .params(kw=query)
    )
    if speaker:
        vector_stmt = vector_stmt.where(func.lower(TranscriptChunk.speaker) == speaker.lower())
        keyword_stmt = keyword_stmt.where(func.lower(TranscriptChunk.speaker) == speaker.lower())

    vector_stmt = vector_stmt.order_by(TranscriptChunk.embedding.cosine_distance(query_vector)).limit(top_k * 3)
    keyword_stmt = keyword_stmt.order_by(
        text("ts_rank_cd(tsv, plainto_tsquery('english', :kw)) DESC")
    ).params(kw=query).limit(top_k * 3)

    vector_rows = (await db.execute(vector_stmt)).scalars().all()
    keyword_rows = (await db.execute(keyword_stmt)).scalars().all()

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
