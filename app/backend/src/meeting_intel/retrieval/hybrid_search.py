"""Hybrid (vector + keyword) retrieval with mandatory tenant_id + meeting_id
filtering, enforced at the query layer (never only in the caller's app-layer
authorization) — see docs/SECURITY.md and search_provider.py.

This module is now a thin dispatcher onto the configured `SearchProvider`
(Azure AI Search or the in-memory dev/test provider) instead of directly
querying PostgreSQL. See docs/MIGRATION_FROM_POSTGRES.md for what changed
and docs/RAG.md for the full ingestion -> retrieval -> answer flow.

`meeting_ids` is always required and always enforced server-side — callers
(the Retrieval Agent) decide which meeting(s) are in scope; this module never
searches beyond the ids and tenant it is given. Cross-meeting search is
therefore only possible when the caller explicitly passes more than one
meeting id, which only happens when `agents.meeting_router` detects an
explicit cross-meeting request.
"""
from __future__ import annotations

from dataclasses import dataclass

from meeting_intel.config import get_settings
from meeting_intel.providers import get_embedding_provider
from .rerank import rerank
from .search_provider import SearchHit, SearchProvider

settings = get_settings()


@dataclass
class RetrievedChunk:
    chunk: SearchHit
    score: float
    vector_rank: int | None
    keyword_rank: int | None


def get_search_provider() -> SearchProvider:
    if settings.search_provider == "azure_search":
        from .azure_search import get_azure_search_provider

        return get_azure_search_provider()
    from .memory_search import get_memory_provider

    return get_memory_provider()


async def hybrid_search(
    db=None,  # kept for call-site compatibility; the search layer needs no DB session
    *,
    tenant_id: str,
    meeting_ids: list[str],
    query: str,
    speaker: str | None = None,
    top_k: int | None = None,
    document_id: str | None = None,
) -> list[RetrievedChunk]:
    if not meeting_ids:
        return []
    if db is not None:
        from .restore_imports import restore_imports
        await restore_imports(db, tenant_id=tenant_id, meeting_ids=meeting_ids, document_id=document_id)
    top_k = top_k or settings.retrieval_top_k
    vector = get_embedding_provider().embed_query(query)

    provider = get_search_provider()
    hits = await provider.hybrid_search(
        tenant_id=tenant_id, meeting_ids=meeting_ids, query=query, vector=vector, speaker=speaker, top_k=min(top_k * 3, 60),
        **({"document_id": document_id} if document_id else {}),
    )
    hits = rerank(hits, query=query, speaker=speaker)[:top_k]
    return [
        RetrievedChunk(chunk=hit, score=hit.score, vector_rank=hit.vector_rank, keyword_rank=hit.keyword_rank)
        for hit in hits
    ]
