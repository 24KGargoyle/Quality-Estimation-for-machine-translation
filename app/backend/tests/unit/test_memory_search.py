"""Unit tests for the in-memory `SearchProvider` — the pgvector/Postgres-FTS
replacement used for local dev and tests. Covers keyword scoring, vector
cosine ranking, RRF hybrid fusion, and mandatory tenant/meeting isolation.
"""
import pytest

from meeting_intel.retrieval.memory_search import InMemorySearchProvider
from meeting_intel.retrieval.search_provider import IndexableChunk

pytestmark = pytest.mark.asyncio


def _chunk(id_, tenant_id="t1", meeting_id="m1", content="hello world", chunk_index=0,
           speaker_name=None, embedding=None):
    return IndexableChunk(
        id=id_, tenant_id=tenant_id, meeting_id=meeting_id, meeting_title="Standup",
        content=content, chunk_index=chunk_index, start_time=0.0, end_time=1.0,
        document_id="doc1", speaker_name=speaker_name, embedding=embedding,
    )


@pytest.fixture
def provider():
    p = InMemorySearchProvider()
    yield p
    p.reset()


async def test_index_and_chunks_for_meeting_returns_in_chunk_order(provider):
    await provider.index_chunks([
        _chunk("c2", chunk_index=1, content="second"),
        _chunk("c1", chunk_index=0, content="first"),
    ])
    hits = await provider.chunks_for_meeting(tenant_id="t1", meeting_id="m1")
    assert [h.id for h in hits] == ["c1", "c2"]


async def test_keyword_search_ranks_by_word_overlap(provider):
    await provider.index_chunks([
        _chunk("c1", content="we decided to ship the feature"),
        _chunk("c2", content="totally unrelated content about lunch"),
    ])
    hits = await provider.keyword_search(tenant_id="t1", meeting_ids=["m1"], query="ship feature", top_k=5)
    assert [h.id for h in hits] == ["c1"]


async def test_keyword_search_speaker_filter(provider):
    await provider.index_chunks([
        _chunk("c1", content="ship the feature", speaker_name="Alice"),
        _chunk("c2", content="ship the feature", speaker_name="Bob"),
    ])
    hits = await provider.keyword_search(tenant_id="t1", meeting_ids=["m1"], query="ship", speaker="alice", top_k=5)
    assert [h.id for h in hits] == ["c1"]


async def test_vector_search_returns_closest_by_cosine(provider):
    await provider.index_chunks([
        _chunk("c1", embedding=[1.0, 0.0]),
        _chunk("c2", embedding=[0.0, 1.0]),
    ])
    hits = await provider.vector_search(tenant_id="t1", meeting_ids=["m1"], vector=[1.0, 0.0], top_k=5)
    assert hits[0].id == "c1"


async def test_vector_search_ignores_chunks_without_embeddings(provider):
    await provider.index_chunks([_chunk("c1", embedding=None)])
    hits = await provider.vector_search(tenant_id="t1", meeting_ids=["m1"], vector=[1.0, 0.0], top_k=5)
    assert hits == []


async def test_hybrid_search_fuses_keyword_and_vector_ranks(provider):
    await provider.index_chunks([
        _chunk("c1", content="ship the feature", embedding=[1.0, 0.0]),
        _chunk("c2", content="totally unrelated", embedding=[0.0, 1.0]),
    ])
    hits = await provider.hybrid_search(
        tenant_id="t1", meeting_ids=["m1"], query="ship feature", vector=[1.0, 0.0], top_k=5
    )
    assert hits[0].id == "c1"
    assert hits[0].vector_rank == 1
    assert hits[0].keyword_rank == 1


async def test_hybrid_search_with_no_meeting_ids_returns_empty(provider):
    hits = await provider.hybrid_search(tenant_id="t1", meeting_ids=[], query="ship", top_k=5)
    assert hits == []


async def test_tenant_isolation_search_never_crosses_tenants(provider):
    await provider.index_chunks([_chunk("c1", tenant_id="tenant-a", content="ship feature")])
    hits = await provider.keyword_search(tenant_id="tenant-b", meeting_ids=["m1"], query="ship", top_k=5)
    assert hits == []


async def test_meeting_isolation_search_never_crosses_meetings(provider):
    await provider.index_chunks([_chunk("c1", meeting_id="m1", content="ship feature")])
    hits = await provider.keyword_search(tenant_id="t1", meeting_ids=["m2"], query="ship", top_k=5)
    assert hits == []


async def test_delete_meeting_removes_all_its_chunks(provider):
    await provider.index_chunks([_chunk("c1", content="ship feature")])
    await provider.delete_meeting(tenant_id="t1", meeting_id="m1")
    hits = await provider.chunks_for_meeting(tenant_id="t1", meeting_id="m1")
    assert hits == []
