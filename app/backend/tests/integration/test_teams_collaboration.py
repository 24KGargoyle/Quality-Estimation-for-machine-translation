"""Integration tests for Discuss-with-Group v2 (Parts 4-14 of the Search
Intelligence + Teams Collaboration upgrade): participant resolution,
existing-group matching, group creation, sending a discussion, and the
security requirements around all of it. Real HTTP API calls; Microsoft
Graph itself is mocked (no live Azure AD tenant is available in this
environment) via `httpx.AsyncClient.request`, mirroring the pattern used for
`AzureAISearchProvider` in `tests/unit/test_azure_search.py`.

§18 test cases covered: resolve meeting participants, find existing group,
existing group exact match, no group found, create group proposal, user
confirmation (no message sent during creation), group creation, send
discussion, unauthorized participant, wrong tenant, unauthorized chat.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from meeting_intel.config import get_settings
from meeting_intel.db.models import GraphUserToken, User, Tenant, Conversation, Message, MessageRole
from cryptography.fernet import Fernet
from meeting_intel.db.session import SessionLocal
from tests.conftest import SAMPLE_VTT, dev_login

pytestmark = pytest.mark.asyncio

ORGANIZER_ENTRA_ID = "11111111-1111-1111-1111-111111111111"
OTHER_ENTRA_ID = "22222222-2222-2222-2222-222222222222"


class _GraphTransport:
    """Records every call and dispatches a canned response by (method, url
    substring) — enough to cover the four delegated Graph endpoints this
    feature uses."""

    def __init__(self):
        self.calls: list[dict] = []
        self.chats_response: dict = {"value": []}
        self.members_response: dict = {"value": [{"userId": ORGANIZER_ENTRA_ID, "displayName": "Organizer"}]}
        self.create_chat_response: dict = {"id": "chat-new-1", "topic": "New Discussion"}

    async def __call__(self, method, url, headers=None, json=None, **kwargs):
        self.calls.append({"method": method, "url": str(url), "json": json})
        if method == "GET" and "/me/chats" in str(url):
            body = self.chats_response
        elif method == "GET" and "/members" in str(url):
            body = self.members_response
        elif method == "POST" and str(url).rstrip("/").endswith("/chats"):
            body = self.create_chat_response
        elif method == "POST" and "/messages" in str(url):
            body = {"id": "msg-1"}
        else:
            body = {"value": []}
        request = httpx.Request(method, str(url))
        return httpx.Response(200, json=body, request=request)


_ORIGINAL_ASYNC_CLIENT_REQUEST = httpx.AsyncClient.request


def _install_graph_transport(monkeypatch, transport: _GraphTransport):
    """Intercepts only real outbound calls to `graph.microsoft.com` (made by
    `GraphClient`'s own short-lived `httpx.AsyncClient()` instances) and
    passes everything else — critically, the test's own ASGI-transport
    `client` fixture, which also happens to be an `httpx.AsyncClient` — through
    to the real implementation unchanged."""

    async def fake_request(self, method, url, headers=None, json=None, **kwargs):
        if "graph.microsoft.com" in str(url):
            return await transport(method, url, headers=headers, json=json)
        return await _ORIGINAL_ASYNC_CLIENT_REQUEST(self, method, url, headers=headers, json=json, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)


async def _configure_graph(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "graph_token_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "ms_tenant_id", "tenant-x")
    from meeting_intel.graph.client import GraphClient
    async def online(self, **kwargs):
        return {"id": "online-1"}
    async def attendance(self, **kwargs):
        return [{"identity": {"id": uid, "tenantId": "tenant-x", "userIdentityType": "aadUser", "displayName": name}, "role": "Attendee"} for uid, name in [(ORGANIZER_ENTRA_ID, "Organizer"), (OTHER_ENTRA_ID, "Other")]]
    monkeypatch.setattr(GraphClient, "find_online_meeting", online)
    monkeypatch.setattr(GraphClient, "get_attendance_report", attendance)
    monkeypatch.setattr(settings, "ms_client_id", "client-x")
    monkeypatch.setattr(settings, "ms_client_secret", "secret-x")


async def _give_user_entra_identity_and_token(user_id: str, entra_id: str) -> None:
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        user.ms_object_id = entra_id
        tenant = await db.get(Tenant, user.tenant_id)
        tenant.ms_tenant_id = "tenant-x"
        cipher = Fernet(get_settings().graph_token_encryption_key.encode())
        db.add(
            GraphUserToken(
                user_id=user_id, access_token=cipher.encrypt(b"fake-access-token").decode(), refresh_token=cipher.encrypt(b"fake-refresh-token").decode(),
                scope="Chat.Read Chat.ReadWrite ChatMessage.Send",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        await db.commit()


async def _setup_meeting_and_organizer(client, *, email="teams1@acme.com", tenant="Acme") -> tuple[str, str, str]:
    """Returns (headers, meeting_id, user_id) for a fresh dev-login user who
    is the organizer of a freshly loaded meeting."""
    token = await dev_login(client, email=email, display_name="Organizer", tenant_name=tenant)
    headers = {"Authorization": f"Bearer {token}"}
    meeting = await client.post(
        "/api/meetings/load", headers=headers, json={"meeting_id": f"m-{email}", "title": "Architecture Discussion", "transcript_vtt": SAMPLE_VTT}
    )
    meeting_id = meeting.json()["id"]
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        user_id = user.id
    return headers, meeting_id, user_id


# --- §4: participant resolution ---


async def test_resolve_meeting_participants_distinguishes_resolved_and_unresolved(client, monkeypatch):
    headers, meeting_id, user_id = await _setup_meeting_and_organizer(client, email="resolve1@acme.com")
    # Unconfigured Graph must not infer attendance from a local login.

    resp = await client.get(f"/api/meetings/{meeting_id}/participants/resolved", headers=headers)
    participants = resp.json()
    assert participants
    assert all(not p["resolved"] and p["user_id"] is None for p in participants)



# --- §5: find existing group ---


async def test_find_teams_group_reports_unavailable_when_graph_not_configured(client):
    headers, meeting_id, _ = await _setup_meeting_and_organizer(client, email="findnograph@acme.com")
    resp = await client.post("/api/discussions/find-teams-group", headers=headers, json={"meeting_id": meeting_id})
    data = resp.json()
    assert data["teams_available"] is False
    assert "not configured" in data["unavailable_reason"].lower()


async def test_find_existing_group_exact_match(client, monkeypatch):
    await _configure_graph(monkeypatch)
    headers, meeting_id, user_id = await _setup_meeting_and_organizer(client, email="findexact@acme.com")
    await _give_user_entra_identity_and_token(user_id, ORGANIZER_ENTRA_ID)

    transport = _GraphTransport()
    transport.members_response["value"].append({"userId": OTHER_ENTRA_ID, "displayName": "Other"})
    transport.chats_response = {
        "value": [
            {
                "id": "chat-existing-1", "chatType": "group", "topic": "Architecture Team",
                "members": [{"userId": ORGANIZER_ENTRA_ID, "displayName": "Organizer"}],
            }
        ]
    }
    _install_graph_transport(monkeypatch, transport)

    resp = await client.post("/api/discussions/find-teams-group", headers=headers, json={"meeting_id": meeting_id})
    data = resp.json()
    assert data["teams_available"] is True
    assert data["existing_group"]["chat_id"] == "chat-existing-1"
    assert data["existing_group"]["match_kind"] == "exact"
    assert data["application_group_id"] is not None


async def test_no_group_found_reports_none_but_still_returns_participants(client, monkeypatch):
    await _configure_graph(monkeypatch)
    headers, meeting_id, user_id = await _setup_meeting_and_organizer(client, email="nogroup@acme.com")
    await _give_user_entra_identity_and_token(user_id, ORGANIZER_ENTRA_ID)

    transport = _GraphTransport()
    transport.chats_response = {"value": []}
    _install_graph_transport(monkeypatch, transport)

    resp = await client.post("/api/discussions/find-teams-group", headers=headers, json={"meeting_id": meeting_id})
    data = resp.json()
    assert data["teams_available"] is True
    assert data["existing_group"] is None
    assert len(data["participants"]) > 0


# --- §6/§7: create group ---


async def test_create_teams_group_rejects_unauthorized_participant_ids(client, monkeypatch):
    await _configure_graph(monkeypatch)
    headers, meeting_id, user_id = await _setup_meeting_and_organizer(client, email="unauth1@acme.com")
    await _give_user_entra_identity_and_token(user_id, ORGANIZER_ENTRA_ID)
    transport = _GraphTransport()
    _install_graph_transport(monkeypatch, transport)

    resp = await client.post(
        "/api/discussions/create-teams-group", headers=headers,
        json={"confirmed": True, "meeting_id": meeting_id, "participant_user_ids": ["not-a-real-participant-id"], "topic": "Test"},
    )
    assert resp.status_code == 400
    assert transport.calls == []  # never even attempted a Graph call


async def test_create_teams_group_proposal_creates_chat_without_sending_a_message(client, monkeypatch):
    """§7.1 'user confirmation': creating the group must not itself send any
    message — sending is a separate, explicitly confirmed step."""
    await _configure_graph(monkeypatch)
    headers, meeting_id, user_id = await _setup_meeting_and_organizer(client, email="create1@acme.com")
    await _give_user_entra_identity_and_token(user_id, ORGANIZER_ENTRA_ID)
    transport = _GraphTransport()
    _install_graph_transport(monkeypatch, transport)

    resp = await client.post(
        "/api/discussions/create-teams-group", headers=headers,
        json={"confirmed": True, "meeting_id": meeting_id, "participant_user_ids": [OTHER_ENTRA_ID], "topic": "Architecture Discussion"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["teams_chat_id"] == "chat-new-1"
    assert data["application_group_id"]

    message_calls = [c for c in transport.calls if "/messages" in c["url"]]
    assert message_calls == []

    async with SessionLocal() as db:
        from meeting_intel.db.models import TeamsMapping

        mapping = (
            await db.execute(select(TeamsMapping).where(TeamsMapping.group_id == data["application_group_id"]))
        ).scalar_one()
        assert mapping.teams_chat_id == "chat-new-1"


# --- §8/§9: send discussion ---


async def test_send_teams_discussion_succeeds_when_caller_is_a_chat_member(client, monkeypatch):
    await _configure_graph(monkeypatch)
    headers, meeting_id, user_id = await _setup_meeting_and_organizer(client, email="send1@acme.com")
    await _give_user_entra_identity_and_token(user_id, ORGANIZER_ENTRA_ID)
    transport = _GraphTransport()
    _install_graph_transport(monkeypatch, transport)

    created = await client.post(
        "/api/discussions/create-teams-group", headers=headers,
        json={"confirmed": True, "meeting_id": meeting_id, "participant_user_ids": [OTHER_ENTRA_ID], "topic": "Architecture Discussion"},
    )
    assert created.status_code == 200, created.text
    group_id = created.json()["application_group_id"]
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        conversation = Conversation(tenant_id=user.tenant_id, user_id=user_id, meeting_id=meeting_id, title="Test")
        db.add(conversation)
        await db.flush()
        message = Message(conversation_id=conversation.id, meeting_id=meeting_id, role=MessageRole.assistant, content="Saved answer <script>blocked</script>")
        db.add(message)
        await db.commit()
        message_id = message.id

    resp = await client.post(
        "/api/discussions/send-teams-discussion", headers=headers,
        json={
            "confirmed": True, "recipient_user_ids": [ORGANIZER_ENTRA_ID], "message_id": message_id, "meeting_id": meeting_id, "group_id": group_id, "topic": "Architecture Discussion",
            "summary": "The team discussed the deployment pipeline.", "question": "Should we proceed?",
            "evidence_speaker": "Chetan Kumar", "evidence_timestamp": "00:00", "evidence_excerpt": "Confirm CrewAI.",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["teams_chat_id"] == "chat-new-1"

    send_calls = [c for c in transport.calls if "/messages" in c["url"]]
    assert len(send_calls) == 1
    assert "Should we proceed?" in send_calls[0]["json"]["body"]["content"]
    assert "Confirm CrewAI" not in send_calls[0]["json"]["body"]["content"]
    assert "Saved answer &lt;script&gt;blocked&lt;/script&gt;" in send_calls[0]["json"]["body"]["content"]


async def test_send_teams_discussion_rejects_caller_not_a_chat_member(client, monkeypatch):
    """§12: re-validates chat membership server-side immediately before
    sending — never trusts a previously-resolved chat_id/group_id alone."""
    await _configure_graph(monkeypatch)
    headers, meeting_id, user_id = await _setup_meeting_and_organizer(client, email="unauthchat@acme.com")
    await _give_user_entra_identity_and_token(user_id, ORGANIZER_ENTRA_ID)
    transport = _GraphTransport()
    _install_graph_transport(monkeypatch, transport)

    created = await client.post(
        "/api/discussions/create-teams-group", headers=headers,
        json={"confirmed": True, "meeting_id": meeting_id, "participant_user_ids": [OTHER_ENTRA_ID], "topic": "Architecture Discussion"},
    )
    assert created.status_code == 200, created.text
    group_id = created.json()["application_group_id"]
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        conversation = Conversation(tenant_id=user.tenant_id, user_id=user_id, meeting_id=meeting_id, title="Test")
        db.add(conversation)
        await db.flush()
        message = Message(conversation_id=conversation.id, meeting_id=meeting_id, role=MessageRole.assistant, content="Saved answer <script>blocked</script>")
        db.add(message)
        await db.commit()
        message_id = message.id

    # Someone else now controls the chat's membership (caller's own Entra id
    # is no longer a member) — the send must be rejected.
    transport.members_response = {"value": [{"userId": OTHER_ENTRA_ID, "displayName": "Someone Else"}]}

    resp = await client.post(
        "/api/discussions/send-teams-discussion", headers=headers,
        json={
            "confirmed": True, "recipient_user_ids": [ORGANIZER_ENTRA_ID], "message_id": message_id, "meeting_id": meeting_id, "group_id": group_id, "topic": "Architecture Discussion",
            "summary": "Summary", "question": "Question?",
        },
    )
    assert resp.status_code == 403


# --- §12: tenant isolation ---


async def test_find_teams_group_enforces_tenant_isolation(client, monkeypatch):
    await _configure_graph(monkeypatch)
    headers_a, meeting_id, user_id = await _setup_meeting_and_organizer(client, email="tenantA@acme.com", tenant="TenantA")
    await _give_user_entra_identity_and_token(user_id, ORGANIZER_ENTRA_ID)

    token_b = await dev_login(client, email="tenantB@other.com", display_name="B", tenant_name="TenantB")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    resp = await client.post("/api/discussions/find-teams-group", headers=headers_b, json={"meeting_id": meeting_id})
    assert resp.status_code == 404

    resp2 = await client.get(f"/api/meetings/{meeting_id}/participants/resolved", headers=headers_b)
    assert resp2.status_code == 404


@pytest.mark.parametrize("confirmed", [None, False])
async def test_creation_requires_confirmation(client, confirmed):
    headers, meeting_id, _ = await _setup_meeting_and_organizer(client, email="confirm@acme.com")
    payload = {"meeting_id": meeting_id, "participant_user_ids": [OTHER_ENTRA_ID], "topic": "Test"}
    if confirmed is not None:
        payload["confirmed"] = confirmed
    response = await client.post("/api/discussions/create-teams-group", headers=headers, json=payload)
    assert response.status_code == 422


async def test_matching_rejects_extra_or_unidentified_members():
    from meeting_intel.teams.group_matcher import find_matching_chat
    chats = [{"id": "c", "chatType": "group", "members": [{"userId": ORGANIZER_ENTRA_ID}, {"userId": OTHER_ENTRA_ID}]}]
    assert find_matching_chat(chats, {ORGANIZER_ENTRA_ID}) is None
    chats[0]["members"][1] = {"id": OTHER_ENTRA_ID}
    assert find_matching_chat(chats, {ORGANIZER_ENTRA_ID, OTHER_ENTRA_ID}) is None


async def test_graph_pagination_rejects_external_host():
    from meeting_intel.graph.client import GraphClient, GraphNotConfiguredError
    with pytest.raises(GraphNotConfiguredError):
        await GraphClient()._delegated_pages("https://example.com/steal", "secret")
