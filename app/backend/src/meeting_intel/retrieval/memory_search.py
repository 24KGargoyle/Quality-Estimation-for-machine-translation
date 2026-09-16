"""A real, working, in-process `SearchProvider` for local development and
tests. This is NOT Azure AI Search and is never presented as such — it
exists because Azure AI Search is unavailable in this environment (and may
be unavailable to any contributor without an Azure subscription), matching
the refinement's explicit "provide a clearly separated development adapter"
requirement (never fake production behavior as if it were the real thing).

Ranking logic (RRF fusion of a keyword rank and a cosine-similarity vector
rank) is carried over unchanged from the pre-refactor `retrieval/hybrid_search.py`
— only the storage location moved (from PostgreSQL rows to an in-process
dict), not the algorithm.
"""
from __future__ import annotations

from collections import defaultdict
from threading import RLock

import numpy as np

from .search_provider import IndexableChunk, SearchHit, SearchProvider


def _rrf(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank)


def _keyword_score(query: str, text: str) -> float:
    query_words = {w for w in query.lower().split() if w}
    if not query_words:
        return 0.0
    text_lower = text.lower()
    return sum(1 for w in query_words if w in text_lower) / len(query_words)


class InMemorySearchProvider(SearchProvider):
    def __init__(self) -> None:
        self._lock = RLock()
        # (tenant_id, meeting_id) -> {chunk_id: IndexableChunk}
        self._store: dict[tuple[str, str], dict[str, IndexableChunk]] = defaultdict(dict)

    def reset(self) -> None:
        """Test-only: clear all indexed data (mirrors clearing SQL tables between tests)."""
        with self._lock:
            self._store.clear()

    async def index_chunks(self, chunks: list[IndexableChunk]) -> None:
        if not chunks:
            return
        with self._lock:
            for chunk in chunks:
                key = (chunk.tenant_id, chunk.meeting_id)
                self._store[key][chunk.id] = chunk

    async def delete_meeting(self, *, tenant_id: str, meeting_id: str) -> None:
        with self._lock:
            self._store.pop((tenant_id, meeting_id), None)

    def _chunks_for_scope(self, tenant_id: str, meeting_ids: list[str]) -> list[IndexableChunk]:
        with self._lock:
            out = []
            for meeting_id in meeting_ids:
                out.extend(self._store.get((tenant_id, meeting_id), {}).values())
            return sorted(out, key=lambda c: (c.meeting_id, c.chunk_index))

    @staticmethod
    def _to_hit(chunk: IndexableChunk, score: float = 0.0) -> SearchHit:
        return SearchHit(
            id=chunk.id, meeting_id=chunk.meeting_id, content=chunk.content, chunk_index=chunk.chunk_index,
            start_time=chunk.start_time, end_time=chunk.end_time, speaker_name=chunk.speaker_name, score=score,
        )

    async def chunks_for_meeting(self, *, tenant_id: str, meeting_id: str) -> list[SearchHit]:
        return [self._to_hit(c) for c in self._chunks_for_scope(tenant_id, [meeting_id])]

    async def keyword_search(
        self, *, tenant_id: str, meeting_ids: list[str], query: str, speaker: str | None = None, top_k: int
    ) -> list[SearchHit]:
        candidates = self._chunks_for_scope(tenant_id, meeting_ids)
        if speaker:
            candidates = [c for c in candidates if (c.speaker_name or "").lower() == speaker.lower()]
        scored = [(c, _keyword_score(query, c.content)) for c in candidates]
        scored = [(c, s) for c, s in scored if s > 0]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [self._to_hit(c, s) for c, s in scored[:top_k]]

    async def vector_search(
        self, *, tenant_id: str, meeting_ids: list[str], vector: list[float], speaker: str | None = None, top_k: int
    ) -> list[SearchHit]:
        candidates = self._chunks_for_scope(tenant_id, meeting_ids)
        if speaker:
            candidates = [c for c in candidates if (c.speaker_name or "").lower() == speaker.lower()]
        embedded = [c for c in candidates if c.embedding]
        if not embedded:
            return []
        matrix = np.array([c.embedding for c in embedded], dtype=np.float32)
        query_vector = np.array(vector, dtype=np.float32)
        similarities = matrix @ query_vector
        order = np.argsort(-similarities)[:top_k]
        return [self._to_hit(embedded[i], float(similarities[i])) for i in order]

    async def hybrid_search(
        self,
        *,
        tenant_id: str,
        meeting_ids: list[str],
        query: str,
        vector: list[float] | None = None,
        speaker: str | None = None,
        top_k: int,
    ) -> list[SearchHit]:
        if not meeting_ids:
            return []
        keyword_hits = await self.keyword_search(
            tenant_id=tenant_id, meeting_ids=meeting_ids, query=query, speaker=speaker, top_k=top_k * 3
        )
        vector_hits = (
            await self.vector_search(
                tenant_id=tenant_id, meeting_ids=meeting_ids, vector=vector, speaker=speaker, top_k=top_k * 3
            )
            if vector is not None
            else []
        )

        fused: dict[str, SearchHit] = {}
        for rank, hit in enumerate(vector_hits, start=1):
            fused[hit.id] = SearchHit(
                id=hit.id, meeting_id=hit.meeting_id, content=hit.content, chunk_index=hit.chunk_index,
                start_time=hit.start_time, end_time=hit.end_time, speaker_name=hit.speaker_name,
                score=_rrf(rank), vector_rank=rank,
            )
        for rank, hit in enumerate(keyword_hits, start=1):
            if hit.id in fused:
                fused[hit.id].score += _rrf(rank)
                fused[hit.id].keyword_rank = rank
            else:
                fused[hit.id] = SearchHit(
                    id=hit.id, meeting_id=hit.meeting_id, content=hit.content, chunk_index=hit.chunk_index,
                    start_time=hit.start_time, end_time=hit.end_time, speaker_name=hit.speaker_name,
                    score=_rrf(rank), keyword_rank=rank,
                )

        ranked = sorted(fused.values(), key=lambda h: h.score, reverse=True)
        return ranked[:top_k]


_provider: InMemorySearchProvider | None = None


def get_memory_provider() -> InMemorySearchProvider:
    global _provider
    if _provider is None:
        _provider = InMemorySearchProvider()
    return _provider
