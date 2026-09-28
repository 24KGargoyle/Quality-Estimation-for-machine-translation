import json

import pytest

from tests.conftest import SAMPLE_VTT, dev_login
from meeting_intel.config import get_settings

pytestmark = pytest.mark.asyncio


async def test_operational_chat_persists_context_and_preserves_contract(client, monkeypatch, tmp_path):
    token = await dev_login(client, email='ops@acme.com', display_name='Ops', tenant_name='Acme')
    headers = {'Authorization': f'Bearer {token}'}
    response = await client.post('/api/meetings/load', headers=headers,
                                json={'meeting_id': 'ops', 'title': 'Operations', 'transcript_vtt': SAMPLE_VTT})
    assert response.status_code == 200
    meeting_id = response.json()['id']
    # Resolve the tenant through the existing database, not assumptions about token shape.
    from meeting_intel.db.session import SessionLocal
    from meeting_intel.db.models import Meeting
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        tenant_id = meeting.tenant_id
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps({'customers': [{'id': 'bp', 'name': 'BP', 'tenant_id': tenant_id,
                                             'meeting_ids': [meeting_id]}], 'records': [
        {'id': 'manager', 'customer_id': 'bp', 'tenant_id': tenant_id, 'source_type': 'customer_master',
         'title': 'Account roster', 'topic': 'account_manager', 'status': 'approved',
         'effective_date': '2020-01-01', 'answer': 'Reviewed Manager'}]}))
    monkeypatch.setattr(get_settings(), 'operational_catalog_path', str(path))
    monkeypatch.setattr(get_settings(), 'operational_enabled', True)
    response = await client.post('/api/chat', headers=headers,
                                json={'meeting_id': meeting_id, 'message': 'Who is the account manager?'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['answer'].startswith('Reviewed Manager') and body['evidence_sufficient']
    assert body['intelligence'] is not None
    assert body['sources'] == [] and body['evidence'] == []
    response = await client.post('/api/chat', headers=headers, json={
        'meeting_id': meeting_id, 'conversation_id': body['conversation_id'],
        'message': 'How do I create a change order?'})
    assert response.status_code == 200
    assert not response.json()['evidence_sufficient']
    assert 'account SME' in response.json()['answer']
    from meeting_intel.retrieval.memory_search import get_memory_provider
    from meeting_intel.retrieval.search_provider import IndexableChunk
    await get_memory_provider().index_chunks([
        IndexableChunk(id=f'customer-{customer}', tenant_id=tenant_id, meeting_id=meeting_id,
                       meeting_title='Operations', content=f'roster evidence {customer}', chunk_index=i,
                       start_time=0, end_time=0, document_id=customer, customer_id=customer)
        for i, customer in enumerate(['bp', 'other'])
    ])
    for endpoint in ['sources', 'search?q=roster']:
        response = await client.get(f'/api/meetings/{meeting_id}/{endpoint}', headers=headers)
        assert response.status_code == 200
        assert response.json()
        assert all(row['chunk_id'] == 'customer-bp' for row in response.json())
    response = await client.get(f'/api/meetings/{meeting_id}/search?q=roster&customer_id=other', headers=headers)
    assert response.status_code == 409
    # Uploaded documents can answer without copying their contents into approved records.
    catalog = json.loads(path.read_text())
    catalog['customers'][0]['uploaded_sources'] = {'DAILY_TASKS': ['bp']}
    path.write_text(json.dumps(catalog))
    monkeypatch.setattr(get_settings(), 'operational_uploaded_evidence_enabled', True)
    await get_memory_provider().index_chunks([IndexableChunk(
        id='bp:daily', tenant_id=tenant_id, meeting_id=meeting_id, meeting_title='Operations',
        content='Update the tracker when a resource changes.', section='Daily / As Needed',
        chunk_index=0, start_time=0, end_time=0, document_id='bp', customer_id='bp', source_file='BP Playbook.docx')])
    response = await client.post('/api/chat', headers=headers, json={
        'meeting_id': meeting_id, 'message': 'What tasks should I do today?'})
    assert response.status_code == 200, response.text
    assert response.json()['evidence_sufficient']
    assert 'when a resource changes' in response.json()['answer']
    assert response.json()['sources'][0]['source_file'] == 'BP Playbook.docx'
    assert 'other' not in response.json()['answer']

async def test_chat_releases_writer_lock_before_generation(client, monkeypatch):
    from sqlalchemy import update
    from meeting_intel.db.models import Meeting
    from meeting_intel.db.session import SessionLocal
    from meeting_intel.agents.answer_agent import AnswerResult
    from meeting_intel.api.routers import chat as chat_router
    token = await dev_login(client, email='lock@test.com', display_name='Lock', tenant_name='Lock')
    headers = {'Authorization': f'Bearer {token}'}
    response = await client.post('/api/meetings/load', headers=headers,
        json={'meeting_id':'lock-test','title':'Lock test','transcript_vtt':SAMPLE_VTT})
    meeting_id = response.json()['id']
    async def answer(db, **kwargs):
        # A separate writer must be able to commit while generation is running.
        import asyncio
        async def write():
            async with SessionLocal() as other:
                await other.execute(update(Meeting).where(Meeting.id==meeting_id).values(title='Updated'))
                await other.commit()
        await asyncio.wait_for(write(), timeout=3)
        return AnswerResult(text='Documented answer', evidence_sufficient=False)
    monkeypatch.setattr(chat_router, 'answer_question', answer)
    response = await client.post('/api/chat', headers=headers,
        json={'meeting_id':meeting_id,'message':'Context?'})
    assert response.status_code == 200, response.text
