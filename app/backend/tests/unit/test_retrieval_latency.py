import asyncio
import pytest
from unittest.mock import AsyncMock, Mock
from meeting_intel.retrieval import restore_imports as restore
from meeting_intel.retrieval import hybrid_search as hybrid

@pytest.mark.asyncio
async def test_unrelated_meeting_restore_not_blocked():
    db=AsyncMock()
    db.execute.return_value=Mock()
    db.execute.return_value.scalars.return_value.all.return_value=[]
    lock=restore._restore_locks[('tenant','video')]
    async with lock:
        await asyncio.wait_for(restore.restore_imports(db,tenant_id='tenant',meeting_ids=['bp']),1)

@pytest.mark.asyncio
async def test_embedding_timeout_preserves_scope(monkeypatch):
    provider=Mock()
    provider.hybrid_search=AsyncMock(return_value=[])
    monkeypatch.setattr(hybrid,'get_search_provider',lambda:provider)
    async def timeout(awaitable,timeout):
        awaitable.close()
        raise TimeoutError
    monkeypatch.setattr(asyncio,'wait_for',timeout)
    await hybrid.hybrid_search(tenant_id='tenant',meeting_ids=['bp-meeting'],query='KT topics',customer_id='bp')
    args=provider.hybrid_search.call_args.kwargs
    assert args['vector'] is None
    assert args['customer_id']=='bp' and args['meeting_ids']==['bp-meeting']
