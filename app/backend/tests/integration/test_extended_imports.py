from email.message import EmailMessage
import io
import zipfile

import pytest

from tests.conftest import dev_login
from tests.integration.test_historical_import import _wait_for_job

pytestmark = pytest.mark.asyncio


async def test_archive_email_and_capabilities(client):
    token = await dev_login(client, email='formats@example.test', display_name='Formats', tenant_name='Formats')
    headers = {'Authorization': f'Bearer {token}'}
    capabilities = await client.get('/api/historical-imports/capabilities', headers=headers)
    assert capabilities.status_code == 200
    formats = {f['extension']: f for f in capabilities.json()['formats']}
    assert {'eml', 'msg', 'mp3', 'mp4', 'ppt', 'xls', 'zip'} <= formats.keys()
    assert formats['mp4']['max_bytes'] == 500 * 1024 * 1024
    message = EmailMessage()
    message['Subject'] = 'Project decision'
    message.set_content('The team agreed to release the pilot on Monday.')
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('decision.eml', message.as_bytes())
        z.writestr('notes.md', '# Project\nThe pilot has been approved.')
    response = await client.post('/api/historical-imports', headers=headers,
        files=[('files', ('Project/materials.zip', archive.getvalue(), 'application/zip'))])
    assert response.status_code == 200, response.text
    assert response.json()['total_files'] == 2
    job = await _wait_for_job(client, headers, response.json()['id'])
    assert job['successful_files'] == 2
    results = await client.get('/api/historical-imports/' + job['id'] + '/results', headers=headers)
    assert {r['file_type'] for r in results.json()['results']} == {'eml', 'md'}


async def test_archive_traversal_rejected_before_job_creation(client):
    token = await dev_login(client, email='security@example.test', display_name='Security', tenant_name='Formats')
    headers = {'Authorization': f'Bearer {token}'}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('../escape.txt', 'unsafe')
    response = await client.post('/api/historical-imports', headers=headers,
        files=[('files', ('bad.zip', archive.getvalue(), 'application/zip'))])
    assert response.status_code == 400
