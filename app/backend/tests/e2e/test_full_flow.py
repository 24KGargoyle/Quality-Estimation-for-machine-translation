"""API-level end-to-end test covering the acceptance-criteria flow
(login -> load meeting -> ask -> follow-up -> feedback -> discuss with group
-> group discussion -> decision).

A true browser E2E (Playwright against the Next.js UI) is not run here — see
docs/TESTING.md for why and what's covered instead.
"""
import pytest

from tests.conftest import SAMPLE_VTT, dev_login

pytestmark = pytest.mark.asyncio


async def test_full_meeting_intelligence_flow(client):
    # 1. Login
    token = await dev_login(client, email="santhosh@acme.com", display_name="Santhosh", tenant_name="Acme")
    headers = {"Authorization": f"Bearer {token}"}

    # 2-5. Provide Meeting ID, load + index meeting
    load = await client.post(
        "/api/meetings/load",
        headers=headers,
        json={"meeting_id": "123456789", "title": "Architecture Discussion", "transcript_vtt": SAMPLE_VTT},
    )
    assert load.status_code == 200
    meeting = load.json()
    assert meeting["status"] == "ready"

    # 6-9. Ask a grounded question, scoped to this meeting only
    ask = await client.post(
        "/api/chat",
        headers=headers,
        json={"meeting_id": meeting["id"], "message": "What did Chetan say about CrewAI?"},
    )
    assert ask.status_code == 200
    answer = ask.json()
    assert answer["speaker_filter"] == "Chetan Kumar"
    assert answer["cross_meeting"] is False
    conversation_id = answer["conversation_id"]
    message_id = answer["message_id"]

    # 10-11. Follow-up question maintains conversation context
    followup = await client.post(
        "/api/chat",
        headers=headers,
        json={
            "meeting_id": meeting["id"],
            "conversation_id": conversation_id,
            "message": "What was his concern?",
        },
    )
    assert followup.status_code == 200
    conv = await client.get(f"/api/conversations/{conversation_id}", headers=headers)
    assert conv.status_code == 200
    assert len(conv.json()["messages"]) == 4  # 2 user + 2 assistant turns

    # 12-13. Feedback
    fb = await client.post(
        f"/api/messages/{message_id}/feedback", headers=headers, json={"rating": "down", "reason": "missing_information"}
    )
    assert fb.status_code == 200

    # 14-16. Discuss with group
    group = await client.post("/api/groups", headers=headers, json={"name": "Architecture Team"})
    group_id = group.json()["id"]
    share = await client.post(
        f"/api/messages/{message_id}/share", headers=headers, json={"group_id": group_id}
    )
    assert share.status_code == 200
    discussion_id = share.json()["discussion_id"]

    # 17-18. Group members continue the discussion, AI assists
    group_msgs = await client.get(f"/api/groups/{group_id}/messages", headers=headers)
    assert len(group_msgs.json()) == 1  # the shared context card

    ai_reply = await client.post(
        f"/api/groups/{group_id}/messages",
        headers=headers,
        json={"content": "Should we proceed with CrewAI or confirm with the client first?", "ask_ai": True},
    )
    assert ai_reply.status_code == 200
    assert len(ai_reply.json()) == 2  # user message + AI response

    # 19-20. Decision / action item detection + human confirmation
    suggestion = await client.get(f"/api/discussions/{discussion_id}/suggested-decision", headers=headers)
    assert suggestion.status_code == 200

    confirm = await client.post(
        f"/api/discussions/{discussion_id}/decisions",
        headers=headers,
        json={
            "decision_text": "Confirm CrewAI requirement with the client before proceeding",
            "action_items": [{"task": "Confirm CrewAI requirement with client", "owner_name": "Chetan Kumar"}],
        },
    )
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "confirmed"

    action_items = await client.get(f"/api/discussions/groups/{group_id}/action-items", headers=headers)
    assert action_items.status_code == 200
    assert action_items.json()[0]["owner_name"] == "Chetan Kumar"
