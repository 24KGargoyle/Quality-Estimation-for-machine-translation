import pytest

from tests.conftest import SAMPLE_VTT, dev_login

pytestmark = pytest.mark.asyncio


async def test_manual_meeting_load_indexes_transcript(client):
    token = await dev_login(client, email="a@acme.com", display_name="Alice", tenant_name="Acme")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/api/meetings/load",
        headers=headers,
        json={"meeting_id": "111222333", "title": "Architecture Discussion", "transcript_vtt": SAMPLE_VTT},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ready"
    assert data["transcript_available"] is True
    assert data["duration_seconds"] == 35
    names = {p["display_name"] for p in data["participants"]}
    assert {"Chetan Kumar", "Ravi Shah", "Alice"} <= names


async def test_meeting_sources_preserve_speaker_and_timestamp(client):
    token = await dev_login(client, email="a@acme.com", display_name="Alice", tenant_name="Acme")
    headers = {"Authorization": f"Bearer {token}"}
    load = await client.post(
        "/api/meetings/load",
        headers=headers,
        json={"meeting_id": "111222333", "title": "Architecture Discussion", "transcript_vtt": SAMPLE_VTT},
    )
    meeting_id = load.json()["id"]

    resp = await client.get(f"/api/meetings/{meeting_id}/sources", headers=headers)
    assert resp.status_code == 200
    chunks = resp.json()
    assert len(chunks) >= 2
    assert all(c["speaker"] for c in chunks)
    assert all("start_seconds" in c and "end_seconds" in c for c in chunks)


async def test_reloading_same_meeting_id_is_idempotent(client):
    """Regression test: submitting the same Meeting ID twice (e.g. a page refresh
    or retry) must not crash with a duplicate-transcript integrity error."""
    token = await dev_login(client, email="a@acme.com", display_name="Alice", tenant_name="Acme")
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"meeting_id": "444555666", "title": "Sprint Planning", "transcript_vtt": SAMPLE_VTT}

    first = await client.post("/api/meetings/load", headers=headers, json=payload)
    assert first.status_code == 200
    meeting_id = first.json()["id"]

    second = await client.post("/api/meetings/load", headers=headers, json=payload)
    assert second.status_code == 200
    assert second.json()["id"] == meeting_id
    assert second.json()["status"] == "ready"

    sources = await client.get(f"/api/meetings/{meeting_id}/sources", headers=headers)
    chunk_count = len(sources.json())
    # Re-loading must not duplicate chunks.
    third = await client.post("/api/meetings/load", headers=headers, json=payload)
    assert third.status_code == 200
    sources_again = await client.get(f"/api/meetings/{meeting_id}/sources", headers=headers)
    assert len(sources_again.json()) == chunk_count


async def test_graph_not_configured_returns_503_without_fabricating_data(client):
    token = await dev_login(client, email="a@acme.com", display_name="Alice", tenant_name="Acme")
    headers = {"Authorization": f"Bearer {token}"}
    # No transcript_vtt provided => attempts the real Graph path, which is unconfigured in this env.
    resp = await client.post(
        "/api/meetings/load", headers=headers, json={"meeting_id": "999999999"}
    )
    assert resp.status_code == 503
