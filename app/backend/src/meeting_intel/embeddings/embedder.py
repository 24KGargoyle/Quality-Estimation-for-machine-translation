"""Local embedding model wrapper (real model, no external API key required).

Loaded lazily and once per process — `sentence-transformers` model loading is
relatively expensive, so this should not run per-request.
"""
from __future__ import annotations

from functools import lru_cache

from meeting_intel.config import get_settings

settings = get_settings()


@lru_cache
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embedding_model)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors = _model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
