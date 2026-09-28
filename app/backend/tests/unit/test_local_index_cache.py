import pytest
from meeting_intel.retrieval.memory_search import InMemorySearchProvider
from meeting_intel.retrieval.search_provider import IndexableChunk
from meeting_intel.retrieval.local_index_cache import load
from meeting_intel.config import get_settings

@pytest.mark.asyncio
async def test_reuse_and_restart_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), 'local_blob_storage_dir', str(tmp_path))
    monkeypatch.setattr(get_settings(), 'file_storage', 'local')
    provider=InMemorySearchProvider()
    c=IndexableChunk(id='d:0',tenant_id='t',meeting_id='m',meeting_title='M',content='Transcript',chunk_index=0,start_time=0,end_time=1,document_id='d',embedding=[1.0])
    await provider.index_chunks([c])
    assert await provider.reuse_document(tenant_id='t',meeting_id='m',document_id='d',expected_count=1)
    provider.reset()
    cached=load('t','m','d')
    assert cached == [c]
    assert load('other','m','d') == []
    await provider.index_chunks(cached)
    assert len(await provider.chunks_for_meeting(tenant_id='t',meeting_id='m')) == 1
