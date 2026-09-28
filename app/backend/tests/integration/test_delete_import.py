import pytest
from tests.conftest import dev_login
from tests.integration.test_historical_import import _wait_for_job

pytestmark = pytest.mark.asyncio

async def test_delete_import_and_reupload(client, tmp_path, monkeypatch):
    from meeting_intel.storage import blob_storage
    monkeypatch.setattr(blob_storage, '_storage', blob_storage.LocalBlobStorage(tmp_path))
    token = await dev_login(client, email='owner@test.com', display_name='Owner', tenant_name='Delete')
    headers = {'Authorization': f'Bearer {token}'}
    async def upload(content):
        response = await client.post('/api/historical-imports', headers=headers,
            files=[('files', ('Project/notes.txt', content, 'text/plain'))])
        return await _wait_for_job(client, headers, response.json()['id'])
    first = await upload(b'The original project decision is approved.')
    second = await upload(b'The separate project decision stays searchable.')
    duplicate = await upload(b'The original project decision is approved.')
    response = await client.delete('/api/historical-imports/' + duplicate['id'], headers=headers)
    assert response.json()['deleted_documents'] == 0
    assert len(list(tmp_path.rglob('*.txt'))) == 2
    other = await dev_login(client, email='other@test.com', display_name='Other', tenant_name='Other')
    assert (await client.delete('/api/historical-imports/' + first['id'],
        headers={'Authorization': f'Bearer {other}'})).status_code == 404
    response = await client.delete('/api/historical-imports/' + first['id'], headers=headers)
    assert response.status_code == 200
    assert response.json()['deleted_documents'] == 1
    assert len(list(tmp_path.rglob('*.txt'))) == 1
    assert (await client.get('/api/historical-imports/' + first['id'], headers=headers)).status_code == 404
    from meeting_intel.retrieval.memory_search import get_memory_provider
    chunks = [c for bucket in get_memory_provider()._store.values() for c in bucket.values()]
    assert chunks and all('original project' not in c.content for c in chunks)
    assert (await upload(b'The original project decision is approved.'))['successful_files'] == 1
    assert (await client.get('/api/historical-imports/' + second['id'], headers=headers)).status_code == 200

async def test_delete_processing_import_rejected(client, monkeypatch):
    from meeting_intel.api.routers import historical_imports
    monkeypatch.setattr(historical_imports, '_launch', lambda *args, **kwargs: None)
    token = await dev_login(client, email='owner@test.com', display_name='Owner', tenant_name='Delete')
    headers = {'Authorization': f'Bearer {token}'}
    response = await client.post('/api/historical-imports', headers=headers,
        files=[('files', ('notes.txt', b'Pending document', 'text/plain'))])
    assert (await client.delete('/api/historical-imports/' + response.json()['id'], headers=headers)).status_code == 409

async def test_delete_failure_retains_retryable_history(client, monkeypatch):
    from meeting_intel.retrieval.hybrid_search import get_search_provider
    token = await dev_login(client, email='owner@test.com', display_name='Owner', tenant_name='Delete')
    headers = {'Authorization': f'Bearer {token}'}
    response = await client.post('/api/historical-imports', headers=headers,
        files=[('files', ('notes.txt', b'A document to retry deleting.', 'text/plain'))])
    job = await _wait_for_job(client, headers, response.json()['id'])
    peer = await dev_login(client, email='peer@test.com', display_name='Peer', tenant_name='Delete')
    assert (await client.delete('/api/historical-imports/' + job['id'],
        headers={'Authorization': f'Bearer {peer}'})).status_code == 403
    async def fail(**kwargs):
        raise RuntimeError('service unavailable')
    monkeypatch.setattr(get_search_provider(), 'delete_document', fail)
    assert (await client.delete('/api/historical-imports/' + job['id'], headers=headers)).status_code == 503
    assert (await client.get('/api/historical-imports/' + job['id'], headers=headers)).status_code == 200
