"""Tests for the real Azure AI Search REST client.

No live Azure resource is used or required — HTTP calls are mocked via
`monkeypatch` on `httpx.AsyncClient.request`. These tests verify: (1) the
provider is inert (raises `SearchNotConfiguredError`, no HTTP call at all)
without AZURE_SEARCH_* configured, (2) the index schema/vector dimensions it
would create, (3) the mandatory tenant_id+meeting_id OData filter on every
query, and (4) OData filter-value escaping. This is NOT a live-Azure test —
see docs/AZURE_SETUP.md and the final report's stated limitations.
"""
import httpx
import pytest

from meeting_intel.retrieval.azure_search import AzureAISearchProvider, _escape_odata
from meeting_intel.retrieval.search_provider import IndexableChunk, SearchNotConfiguredError

pytestmark = pytest.mark.asyncio


async def test_document_filter_is_applied_before_ranking(monkeypatch):
    provider = _configured_provider(monkeypatch)
    captured = {}

    async def request(method, path, json_body=None):
        captured.update(json_body)
        return {"value": []}

    monkeypatch.setattr(provider, "_request", request)
    await provider.hybrid_search(
        tenant_id="tenant", meeting_ids=["meeting"], query="pilot",
        top_k=5, document_id="hist:abc'123",
    )
    assert "tenant_id eq 'tenant'" in captured["filter"]
    assert "document_id eq 'hist:abc''123'" in captured["filter"]


def _configured_provider(monkeypatch):
    # `get_settings()` is process-wide (lru_cache'd), so every attribute we
    # touch is set via `monkeypatch.setattr` on the shared object — pytest
    # reverts it after the test, preventing cross-test leakage.
    provider = AzureAISearchProvider()
    monkeypatch.setattr(provider.settings, "azure_search_endpoint", "https://example.search.windows.net")
    monkeypatch.setattr(provider.settings, "azure_search_api_key", "fake-key")
    monkeypatch.setattr(provider.settings, "azure_search_index", "transcript-chunks")
    monkeypatch.setattr(provider.settings, "embedding_provider", "local")
    monkeypatch.setattr(provider.settings, "embedding_dim", 384)
    return provider


class _RecordingTransport:
    """Captures every outgoing request and returns a canned JSON response."""

    def __init__(self, json_response=None):
        self.calls: list[dict] = []
        self.json_response = json_response if json_response is not None else {"value": []}

    async def __call__(self, method, url, headers=None, json=None, **kwargs):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        request = httpx.Request(method, url)
        return httpx.Response(200, json=self.json_response, request=request)


def _install_transport(monkeypatch, transport: _RecordingTransport):
    async def fake_request(self, method, url, headers=None, json=None, **kwargs):
        return await transport(method, url, headers=headers, json=json)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)


async def test_unconfigured_provider_raises_before_any_http_call(monkeypatch):
    calls = []

    async def fake_request(self, *args, **kwargs):
        calls.append(1)
        raise AssertionError("should never be called when unconfigured")

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)

    provider = AzureAISearchProvider()
    monkeypatch.setattr(provider.settings, "azure_search_endpoint", None)
    monkeypatch.setattr(provider.settings, "azure_search_api_key", None)

    with pytest.raises(SearchNotConfiguredError):
        await provider.keyword_search(tenant_id="t1", meeting_ids=["m1"], query="hello", top_k=5)
    assert calls == []


async def test_ensure_index_sends_expected_schema_and_vector_dimensions(monkeypatch):
    transport = _RecordingTransport()
    _install_transport(monkeypatch, transport)
    provider = _configured_provider(monkeypatch)

    await provider.ensure_index()

    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "PUT"
    field_names = {f["name"] for f in call["json"]["fields"]}
    assert field_names == {
        "id", "tenant_id", "meeting_id", "meeting_join_id", "meeting_title", "meeting_date",
        "speaker_id", "speaker_name", "start_time", "end_time", "content", "content_type",
        "chunk_index", "source", "document_id", "embedding",
        "source_file", "relative_path", "file_type", "document_type",
        "page_number", "sheet_name", "slide_number", "section",
    }
    embedding_field = next(f for f in call["json"]["fields"] if f["name"] == "embedding")
    assert embedding_field["dimensions"] == 384
    assert "vectorSearch" in call["json"]
    assert "semanticSearch" in call["json"]


async def test_ensure_index_uses_azure_openai_embedding_dimensions_when_that_provider_is_active(monkeypatch):
    transport = _RecordingTransport()
    _install_transport(monkeypatch, transport)
    provider = _configured_provider(monkeypatch)
    monkeypatch.setattr(provider.settings, "embedding_provider", "azure_openai")
    monkeypatch.setattr(provider.settings, "azure_openai_embedding_dimensions", 1536)

    await provider.ensure_index()

    embedding_field = next(f for f in transport.calls[0]["json"]["fields"] if f["name"] == "embedding")
    assert embedding_field["dimensions"] == 1536


async def test_ensure_index_requires_explicit_azure_openai_embedding_dimensions(monkeypatch):
    provider = _configured_provider(monkeypatch)
    monkeypatch.setattr(provider.settings, "embedding_provider", "azure_openai")
    monkeypatch.setattr(provider.settings, "azure_openai_embedding_dimensions", None)
    with pytest.raises(SearchNotConfiguredError):
        await provider.ensure_index()


async def test_index_chunks_sends_merge_or_upload_actions(monkeypatch):
    transport = _RecordingTransport()
    _install_transport(monkeypatch, transport)
    provider = _configured_provider(monkeypatch)

    chunk = IndexableChunk(
        id="c1", tenant_id="t1", meeting_id="m1", meeting_title="Standup", content="hello",
        chunk_index=0, start_time=0.0, end_time=1.0, document_id="doc1", embedding=[0.1, 0.2],
    )
    await provider.index_chunks([chunk])

    # First call is ensure_index (PUT), second is the actual doc upload.
    upload_call = transport.calls[1]
    assert upload_call["method"] == "POST"
    assert "/docs/index" in upload_call["url"]
    action = upload_call["json"]["value"][0]
    assert action["@search.action"] == "mergeOrUpload"
    assert action["id"] == "c1"
    assert action["tenant_id"] == "t1"
    assert action["embedding"] == [0.1, 0.2]


async def test_keyword_search_always_includes_tenant_and_meeting_filter(monkeypatch):
    transport = _RecordingTransport()
    _install_transport(monkeypatch, transport)
    provider = _configured_provider(monkeypatch)

    await provider.keyword_search(tenant_id="tenant-1", meeting_ids=["meeting-1", "meeting-2"], query="ship", top_k=5)

    body = transport.calls[0]["json"]
    assert "tenant_id eq 'tenant-1'" in body["filter"]
    assert "meeting_id eq 'meeting-1'" in body["filter"]
    assert "meeting_id eq 'meeting-2'" in body["filter"]


async def test_hybrid_search_uses_semantic_query_type_and_vector_query(monkeypatch):
    transport = _RecordingTransport()
    _install_transport(monkeypatch, transport)
    provider = _configured_provider(monkeypatch)

    await provider.hybrid_search(
        tenant_id="t1", meeting_ids=["m1"], query="what did we decide", vector=[0.1, 0.2], top_k=5
    )

    body = transport.calls[0]["json"]
    assert body["queryType"] == "semantic"
    assert body["vectorQueries"][0]["vector"] == [0.1, 0.2]
    assert "tenant_id eq 't1'" in body["filter"]
    assert "meeting_id eq 'm1'" in body["filter"]


async def test_hybrid_search_with_no_meeting_ids_returns_empty_without_http_call(monkeypatch):
    calls = []

    async def fake_request(self, *args, **kwargs):
        calls.append(1)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    provider = _configured_provider(monkeypatch)

    hits = await provider.hybrid_search(tenant_id="t1", meeting_ids=[], query="ship", top_k=5)
    assert hits == []
    assert calls == []


async def test_odata_escaping_prevents_filter_injection():
    assert _escape_odata("O'Brien") == "O''Brien"
    assert _escape_odata("normal") == "normal"


async def test_speaker_filter_is_escaped_in_scope_filter(monkeypatch):
    transport = _RecordingTransport()
    _install_transport(monkeypatch, transport)
    provider = _configured_provider(monkeypatch)

    await provider.keyword_search(
        tenant_id="t1", meeting_ids=["m1"], query="ship", speaker="O'Brien", top_k=5
    )
    body = transport.calls[0]["json"]
    assert "speaker_name eq 'O''Brien'" in body["filter"]


async def test_request_failure_is_surfaced_as_not_configured_error(monkeypatch):
    async def failing_request(self, method, url, headers=None, json=None, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.AsyncClient, "request", failing_request)
    provider = _configured_provider(monkeypatch)

    with pytest.raises(SearchNotConfiguredError):
        await provider.keyword_search(tenant_id="t1", meeting_ids=["m1"], query="ship", top_k=5)
