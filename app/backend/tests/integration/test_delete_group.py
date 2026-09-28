import pytest
from tests.conftest import dev_login

pytestmark = pytest.mark.asyncio

async def test_delete_group_owner_and_tenant_isolation(client):
    async def login(email, tenant):
        token = await dev_login(client,email=email,display_name=email,tenant_name=tenant)
        return {'Authorization': f'Bearer {token}'}
    owner = await login('owner@test.com','GroupTest')
    peer = await login('peer@test.com','GroupTest')
    outsider = await login('other@test.com','Other')
    group = (await client.post('/api/groups',headers=owner,json={'name':'Delete me'})).json()
    keep = (await client.post('/api/groups',headers=owner,json={'name':'Keep me'})).json()
    await client.post('/api/groups/'+group['id']+'/members',headers=owner,json={'email':'peer@test.com'})
    path = '/api/groups/'+group['id']
    assert (await client.delete(path,headers=peer)).status_code == 403
    assert (await client.delete(path,headers=outsider)).status_code == 404
    from meeting_intel.db.session import SessionLocal
    from meeting_intel.db.models import Message, MessageRole
    async with SessionLocal() as db:
        db.add(Message(group_id=group['id'],role=MessageRole.user,content='Group message'))
        await db.commit()
    response = await client.delete(path,headers=owner)
    assert response.status_code == 200, response.text
    assert [g['id'] for g in (await client.get('/api/groups',headers=owner)).json()] == [keep['id']]
    assert (await client.get(path+'/messages',headers=owner)).status_code == 404
    from sqlalchemy import select
    async with SessionLocal() as db:
        assert not (await db.execute(select(Message).where(Message.group_id==group['id']))).scalars().all()
