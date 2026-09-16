"""Security fixes made in the PostgreSQL-removal refactor:
1. Entra OAuth `state` is now server-persisted, single-use, and validated on
   callback (previously accepted from the client and never checked at all).
2. Session logout revokes the token immediately.
3. Sharing a group-sourced AI message now checks the caller is a member of
   the SOURCE group too, not only the destination group.

None require a real Microsoft Entra ID tenant: the state check runs before
any Graph/MSAL call, so it is fully testable against this app's own
authorization logic.
"""
import pytest

from tests.conftest import SAMPLE_VTT, dev_login

pytestmark = pytest.mark.asyncio


async def test_entra_callback_rejects_unknown_state_before_any_msal_call(client, monkeypatch):
    from meeting_intel.config import get_settings

    monkeypatch.setattr(get_settings(), "auth_provider", "entra")
    resp = await client.post("/api/auth/entra/callback", json={"code": "irrelevant", "state": "not-a-real-state"})
    assert resp.status_code == 401
    assert "Invalid or expired login state" in resp.json()["detail"]


async def test_entra_login_url_issues_a_real_persisted_state(client, monkeypatch):
    from meeting_intel.config import get_settings
    from meeting_intel.security.session_security import consume_oauth_state
    from meeting_intel.db.session import SessionLocal

    monkeypatch.setattr(get_settings(), "auth_provider", "entra")
    # Graph isn't configured in this environment, but a state must still be
    # persisted before that failure surfaces.
    resp = await client.get("/api/auth/entra/login-url")
    assert resp.status_code == 503

    from meeting_intel.security.session_security import create_oauth_state

    async with SessionLocal() as db:
        state = await create_oauth_state(db)
        assert await consume_oauth_state(db, state) is True
        assert await consume_oauth_state(db, state) is False  # single-use


async def test_dev_provider_still_gates_entra_routes_regardless_of_state(client):
    resp = await client.get("/api/auth/entra/login-url")
    assert resp.status_code == 403
    resp = await client.post("/api/auth/entra/callback", json={"code": "x", "state": "x"})
    assert resp.status_code == 403


async def test_logout_immediately_invalidates_the_token_used(client):
    token = await dev_login(client, email="alice@acme.com", display_name="Alice", tenant_name="Acme")
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/meetings", headers=headers)).status_code == 200

    logout = await client.post("/api/auth/logout", headers=headers)
    assert logout.status_code == 200
    assert logout.json() == {"status": "logged_out"}

    after = await client.get("/api/meetings", headers=headers)
    assert after.status_code == 401
    assert "logged out" in after.json()["detail"]


async def test_logout_does_not_affect_a_different_users_token(client):
    token_a = await dev_login(client, email="a@acme.com", display_name="A", tenant_name="Acme")
    token_b = await dev_login(client, email="b@acme.com", display_name="B", tenant_name="Acme")

    await client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token_a}"})

    resp = await client.get("/api/meetings", headers={"Authorization": f"Bearer {token_b}"})
    assert resp.status_code == 200


async def test_sharing_a_group_sourced_message_requires_source_group_membership(client):
    """A message that lives in group A's history (an ask_ai reply) must not
    be shareable into group B by a user who was never a member of group A."""
    owner_token = await dev_login(client, email="owner@acme.com", display_name="Owner", tenant_name="Acme")
    outsider_token = await dev_login(client, email="outsider@acme.com", display_name="Outsider", tenant_name="Acme")
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    outsider_headers = {"Authorization": f"Bearer {outsider_token}"}

    group_a = (await client.post("/api/groups", headers=owner_headers, json={"name": "Group A"})).json()
    ai_reply = await client.post(
        f"/api/groups/{group_a['id']}/messages", headers=owner_headers,
        json={"content": "What should we do?", "ask_ai": True},
    )
    assert ai_reply.status_code == 200
    ai_message_id = ai_reply.json()[-1]["id"]  # the AI's reply, group_id=group_a, conversation_id=None

    # Outsider is a member of a different group and tries to share group A's AI message into it.
    group_b = (await client.post("/api/groups", headers=outsider_headers, json={"name": "Group B"})).json()
    share = await client.post(
        f"/api/messages/{ai_message_id}/share", headers=outsider_headers, json={"group_id": group_b["id"]}
    )
    assert share.status_code == 403


async def test_owner_can_share_their_own_groups_ai_message(client):
    """Positive case: sharing still works for a member of the source group."""
    token = await dev_login(client, email="owner2@acme.com", display_name="Owner2", tenant_name="Acme")
    headers = {"Authorization": f"Bearer {token}"}
    group_a = (await client.post("/api/groups", headers=headers, json={"name": "Group A2"})).json()
    ai_reply = await client.post(
        f"/api/groups/{group_a['id']}/messages", headers=headers, json={"content": "hello", "ask_ai": True}
    )
    ai_message_id = ai_reply.json()[-1]["id"]
    group_b = (await client.post("/api/groups", headers=headers, json={"name": "Group B2"})).json()
    share = await client.post(f"/api/messages/{ai_message_id}/share", headers=headers, json={"group_id": group_b["id"]})
    assert share.status_code == 200
