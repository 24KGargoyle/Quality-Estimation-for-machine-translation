import pytest

from tests.conftest import SAMPLE_VTT, dev_login

pytestmark = pytest.mark.asyncio


async def test_no_token_is_rejected(client):
    resp = await client.get("/api/meetings")
    assert resp.status_code == 401


async def test_invalid_token_is_rejected(client):
    resp = await client.get("/api/meetings", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


async def test_cross_tenant_user_cannot_access_meeting_by_id(client):
    owner_token = await dev_login(client, email="owner@acme.com", display_name="Owner", tenant_name="Acme")
    outsider_token = await dev_login(client, email="outsider@other.com", display_name="Outsider", tenant_name="Other")

    load = await client.post(
        "/api/meetings/load",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"meeting_id": "555", "title": "Private Meeting", "transcript_vtt": SAMPLE_VTT},
    )
    meeting_id = load.json()["id"]

    resp = await client.get(f"/api/meetings/{meeting_id}", headers={"Authorization": f"Bearer {outsider_token}"})
    assert resp.status_code == 404  # never reveal existence to an unauthorized caller

    chat_resp = await client.post(
        "/api/chat",
        headers={"Authorization": f"Bearer {outsider_token}"},
        json={"meeting_id": meeting_id, "message": "What was discussed?"},
    )
    assert chat_resp.status_code == 404


async def test_non_participant_same_tenant_cannot_access_meeting(client):
    owner_token = await dev_login(client, email="owner@acme.com", display_name="Owner", tenant_name="Acme")
    colleague_token = await dev_login(client, email="colleague@acme.com", display_name="Colleague", tenant_name="Acme")

    load = await client.post(
        "/api/meetings/load",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"meeting_id": "555", "title": "Private Meeting", "transcript_vtt": SAMPLE_VTT},
    )
    meeting_id = load.json()["id"]

    resp = await client.get(f"/api/meetings/{meeting_id}", headers={"Authorization": f"Bearer {colleague_token}"})
    assert resp.status_code == 403


async def test_user_cannot_read_another_users_private_conversation(client):
    token_a = await dev_login(client, email="a@acme.com", display_name="A", tenant_name="Acme")
    token_b = await dev_login(client, email="b@acme.com", display_name="B", tenant_name="Acme")

    load = await client.post(
        "/api/meetings/load",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"meeting_id": "555", "title": "Meeting", "transcript_vtt": SAMPLE_VTT},
    )
    meeting_id = load.json()["id"]

    chat = await client.post(
        "/api/chat",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"meeting_id": meeting_id, "message": "What did Chetan say?"},
    )
    conversation_id = chat.json()["conversation_id"]

    resp = await client.get(
        f"/api/conversations/{conversation_id}", headers={"Authorization": f"Bearer {token_b}"}
    )
    assert resp.status_code == 404


async def test_non_member_cannot_post_to_group(client):
    token_a = await dev_login(client, email="a@acme.com", display_name="A", tenant_name="Acme")
    token_b = await dev_login(client, email="b@acme.com", display_name="B", tenant_name="Acme")

    group = await client.post(
        "/api/groups", headers={"Authorization": f"Bearer {token_a}"}, json={"name": "Private Group"}
    )
    group_id = group.json()["id"]

    resp = await client.post(
        f"/api/groups/{group_id}/messages",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"content": "hi"},
    )
    assert resp.status_code == 403
