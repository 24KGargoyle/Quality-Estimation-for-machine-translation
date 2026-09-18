"""A deterministic reranking pass over already-fused hybrid search hits
(§1.4 of the Search Intelligence upgrade — "Hybrid Retrieval -> Reranking ->
Top Evidence"). No cross-encoder/ML reranker is used — the fusion step
(Reciprocal Rank Fusion, or Azure AI Search's own semantic ranking) already
produces a reasonable base ordering; this pass makes it precise for the one
signal RRF can't see: whether the caller already resolved a specific speaker
from the question (`agents/query_understanding.py`), which should be
authoritative for a person-scoped question. It never invents relevance —
every boost is a real match on the hit's own content or metadata.
"""
from __future__ import annotations

import re
from dataclasses import replace

from .search_provider import SearchHit

_SPEAKER_MATCH_BOOST = 1.0
_KEYWORD_MATCH_BOOST = 0.05
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "did", "do", "does", "what", "who",
    "when", "where", "why", "how", "to", "of", "in", "on", "for", "and", "or", "about",
    "say", "said", "mention", "mentioned", "think", "that", "this",
}


def _query_keywords(query: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9]+", query.lower())
    return [w for w in words if w not in _STOPWORDS and len(w) > 2]


def rerank(hits: list[SearchHit], *, query: str, speaker: str | None) -> list[SearchHit]:
    if not hits:
        return hits
    keywords = _query_keywords(query)
    boosted: list[SearchHit] = []
    for hit in hits:
        score = hit.score
        if speaker and hit.speaker_name and hit.speaker_name.lower() == speaker.lower():
            score += _SPEAKER_MATCH_BOOST
        content_lower = hit.content.lower()
        exact_matches = sum(1 for kw in keywords if kw in content_lower)
        score += exact_matches * _KEYWORD_MATCH_BOOST
        boosted.append(replace(hit, score=score))
    return sorted(boosted, key=lambda h: h.score, reverse=True)
