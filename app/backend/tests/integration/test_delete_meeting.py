import pytest
from tests.conftest import dev_login
from tests.integration.test_historical_import import _wait_for_job

pytestmark = pytest.mark.asyncio

async def test_delete_meeting_removes_sources_and_allows_reimport(client, tmp_path, monkeypatch):
    from meeting_intel.storage import blob_storage
    from meeting_intel.retrieval.memory_search import get_memory_provider
    monkeypatch.setattr(blob_storage, '_storage', blob_storage.LocalBlobStorage(tmp_path))
    token = await dev_login(client, email='owner@test.com', display_name='Owner', tenant_name='Delete')
    headers = {'Authorization': f'Bearer {token}'}
    async def upload():
        response = await client.post('/api/historical-imports', headers=headers,
            files=[('files', ('Project/notes.txt', b'The project launch is approved.', 'text/plain'))])
        return await _wait_for_job(client, headers, response.json()['id'])
    job = await upload()
    meeting = (await client.get('/api/meetings', headers=headers)).json()[0]
    other = await dev_login(client, email='other@test.com', display_name='Other', tenant_name='Other')
    assert (await client.delete('/api/meetings/' + meeting['id'], headers={'Authorization': f'Bearer {other}'})).status_code == 404
    peer = await dev_login(client, email='peer@test.com', display_name='Peer', tenant_name='Delete')
    assert (await client.delete('/api/meetings/' + meeting['id'], headers={'Authorization': f'Bearer {peer}'})).status_code == 403
    response = await client.delete('/api/meetings/' + meeting['id'], headers=headers)
    assert response.status_code == 200, response.text
    assert (await client.get('/api/meetings', headers=headers)).json() == []
    assert not list(tmp_path.rglob('*.txt'))
    assert not any(get_memory_provider()._store.values())
    assert (await client.get('/api/historical-imports/' + job['id'], headers=headers)).status_code == 200
    assert (await upload())['successful_files'] == 1

async def test_delete_manual_meeting_failure_then_retry(client, monkeypatch):
    from meeting_intel.retrieval.hybrid_search import get_search_provider
    token = await dev_login(client, email='owner@test.com', display_name='Owner', tenant_name='Delete')
    headers = {'Authorization': f'Bearer {token}'}
    response = await client.post('/api/meetings/load', headers=headers, json={
        'meeting_id': '123456789', 'title': 'Manual',
        'transcript_vtt': 'WEBVTT\n\n00:00:00.000 --> 00:00:05.000\n<v Alice>Launch next week.</v>\n',
    })
    assert response.status_code == 200, response.text
    path = '/api/meetings/' + response.json()['id']
    provider = get_search_provider()
    original = provider.delete_meeting
    async def fail(**kwargs):
        raise RuntimeError('unavailable')
    monkeypatch.setattr(provider, 'delete_meeting', fail)
    assert (await client.delete(path, headers=headers)).status_code == 503
    assert (await client.get(path, headers=headers)).status_code == 200
    monkeypatch.setattr(provider, 'delete_meeting', original)
    assert (await client.delete(path, headers=headers)).status_code == 200
    assert (await client.get(path, headers=headers)).status_code == 404
