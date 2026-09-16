"""`LLMProvider` / `EmbeddingProvider` abstractions.

Anthropic (`llm/client.py`) and the local sentence-transformers model
(`embeddings/embedder.py`) remain the default, working implementations —
real today, and (for the LLM) require only `ANTHROPIC_API_KEY`. The Azure
OpenAI implementations below are real too (actual SDK calls against
`AsyncAzureOpenAI`/`AzureOpenAI`) but inert without `AZURE_OPENAI_*`
credentials, which are not available in this environment — selecting them
(`LLM_PROVIDER=azure_openai` / `EMBEDDING_PROVIDER=azure_openai`) is a real,
working configuration switch, never a pretend one. Deployment names and
embedding dimensions are always read from configuration, never hard-coded.

Business logic (`agents/answer_agent.py`, `agents/discussion_agent.py`,
`agents/decision_agent.py`, `retrieval/hybrid_search.py`,
`ingestion/pipeline.py`) depends on `get_llm_provider()`/
`get_embedding_provider()`, never directly on a vendor SDK.
"""
from __future__ import annotations

from typing import Protocol

from meeting_intel.config import get_settings
from meeting_intel.llm.client import LLMNotConfiguredError, LLMResult


class LLMProvider(Protocol):
    async def complete(self, *, system: str, messages: list[dict], max_tokens: int = 1024) -> LLMResult: ...


class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class AnthropicLLMProvider:
    async def complete(self, *, system: str, messages: list[dict], max_tokens: int = 1024) -> LLMResult:
        from meeting_intel.llm.client import complete

        return await complete(system=system, messages=messages, max_tokens=max_tokens)


class LocalEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        from meeting_intel.embeddings.embedder import embed_texts

        return embed_texts(texts)

    def embed_query(self, text: str) -> list[float]:
        from meeting_intel.embeddings.embedder import embed_query

        return embed_query(text)


class AzureOpenAILLMProvider:
    """Real Azure OpenAI chat-completions call. Raises the same
    `LLMNotConfiguredError` the Anthropic provider does, so callers (e.g.
    `agents/answer_agent.py`) need no provider-specific error handling."""

    async def complete(self, *, system: str, messages: list[dict], max_tokens: int = 1024) -> LLMResult:
        import time

        settings = get_settings()
        if not settings.llm_configured:
            raise LLMNotConfiguredError(
                "Azure OpenAI is not configured. Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, "
                "AZURE_OPENAI_CHAT_DEPLOYMENT."
            )
        from openai import AsyncAzureOpenAI

        client = AsyncAzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )
        start = time.perf_counter()
        response = await client.chat.completions.create(
            model=settings.azure_openai_chat_deployment,
            messages=[{"role": "system", "content": system}, *messages],
            max_tokens=max_tokens,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        text = response.choices[0].message.content or ""
        return LLMResult(text=text, latency_ms=latency_ms, model=settings.azure_openai_chat_deployment)


class AzureOpenAIEmbeddingProvider:
    """Real Azure OpenAI embeddings call. Validates the returned vector
    dimension against `AZURE_OPENAI_EMBEDDING_DIMENSIONS` (never inferred
    from the deployment name, which is just an alias)."""

    def _client(self):
        settings = get_settings()
        if not settings.embedding_configured:
            raise LLMNotConfiguredError(
                "Azure OpenAI embeddings are not configured. Set AZURE_OPENAI_ENDPOINT, "
                "AZURE_OPENAI_API_KEY, AZURE_OPENAI_EMBEDDING_DEPLOYMENT, "
                "AZURE_OPENAI_EMBEDDING_DIMENSIONS."
            )
        from openai import AzureOpenAI

        return AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        settings = get_settings()
        client = self._client()
        response = client.embeddings.create(model=settings.azure_openai_embedding_deployment, input=texts)
        rows = sorted(response.data, key=lambda d: d.index)
        vectors = [list(row.embedding) for row in rows]
        for vector in vectors:
            if len(vector) != settings.azure_openai_embedding_dimensions:
                raise LLMNotConfiguredError(
                    "Azure OpenAI embedding dimension differs from AZURE_OPENAI_EMBEDDING_DIMENSIONS"
                )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    if settings.llm_provider == "azure_openai":
        return AzureOpenAILLMProvider()
    return AnthropicLLMProvider()


def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    if settings.embedding_provider == "azure_openai":
        return AzureOpenAIEmbeddingProvider()
    return LocalEmbeddingProvider()
