import pytest

from tests.conftest import dev_login

pytestmark = pytest.mark.asyncio


async def test_group_members_permissions_and_access(client):
    async def login(email, tenant="Acme"):
        token = await dev_login(client, email=email, display_name=email.split("@")[0], tenant_name=tenant)
        return {"Authorization": f"Bearer {token}"}

    admin = await login("admin@acme.com")
    owner = await login("owner@acme.com")
    member = await login("member@acme.com")
    outsider = await login("outsider@other.com", "Other")
    group = (await client.post("/api/groups", headers=owner, json={"name": "Team"})).json()
    url = f"/api/groups/{group['id']}/members"
    assert (await client.get(url)).status_code == 401
    assert (await client.get(url, headers=member)).status_code == 403
    assert (await client.get(url, headers=outsider)).status_code == 404
    await client.post(f"/api/groups/{group['id']}/messages", headers=owner, json={"content": "Welcome"})

    result = await client.post(url, headers=owner, json={"email": " MEMBER@ACME.COM "})
    assert result.status_code == 200
    assert result.json()["can_manage"] is True
    assert {u["email"] for u in result.json()["members"]} == {"owner@acme.com", "member@acme.com"}
    duplicate = await client.post(url, headers=owner, json={"email": "member@acme.com"})
    assert len(duplicate.json()["members"]) == 2
    view = (await client.get(url, headers=member)).json()
    assert view["can_manage"] is False
    history = await client.get(f"/api/groups/{group['id']}/messages", headers=member)
    assert history.status_code == 200
    assert history.json()[0]["content"] == "Welcome"
    assert (await client.post(url, headers=member, json={"email": "admin@acme.com"})).status_code == 403
    assert (await client.post(url, headers=owner, json={"email": "outsider@other.com"})).status_code == 404
    assert (await client.post(url, headers=outsider, json={"email": "outsider@other.com"})).status_code == 404
    assert (await client.post(url, headers=owner, json={"email": "unknown@acme.com"})).status_code == 404
    assert (await client.post(url, headers=admin, json={"email": "admin@acme.com"})).status_code == 200
    groups = (await client.get("/api/groups", headers=member)).json()
    assert groups[0]["member_count"] == 3
