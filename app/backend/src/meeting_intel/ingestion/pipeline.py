"""Meeting ingestion: Graph lookup / manual transcript -> parse -> chunk -> embed -> index.

Two ingestion paths:
  1. Graph-backed (`load_meeting_from_graph`) — the primary path once a real
     Azure AD app registration exists. Raises `GraphNotConfiguredError` today
     because no such registration is available in this environment (see
     ARCHITECTURE_ASSESSMENT.md) — the router turns that into a 503 rather
     than fabricating meeting data.
  2. Manual transcript upload (`load_meeting_manual`) — a real, documented
     fallback for meetings whose transcript isn't reachable via Graph (e.g.
     transcription wasn't enabled) and for exercising the full pipeline in
     this environment without live Azure credentials. It is explicitly
     labeled as such via `TranscriptSource.manual_upload` and is never
     presented to the user as Graph-sourced data.

Indexing itself (parse -> chunk -> embed -> persist) is identical for both
paths and always preserves meeting_id/speaker/timestamp metadata per chunk.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.auth.entra import GraphNotConfiguredError
from meeting_intel.db.models import (
    Meeting,
    MeetingParticipant,
    MeetingStatus,
    MeetingTranscript,
    ParticipantRole,
    TranscriptSource,
    User,
)
from meeting_intel.graph.client import GraphMeetingNotFoundError, get_graph_client
from meeting_intel.ingestion.chunker import chunk_cues
from meeting_intel.ingestion.transcript_parser import parse_vtt
from meeting_intel.providers import get_embedding_provider
from meeting_intel.retrieval.hybrid_search import get_search_provider
from meeting_intel.retrieval.search_provider import IndexableChunk

logger = logging.getLogger("meeting_intel.ingestion")


async def _get_or_create_meeting(
    db: AsyncSession, *, tenant_id: str, ms_meeting_id: str, title: str, organizer_id: str | None
) -> Meeting:
    meeting = (
        await db.execute(
            select(Meeting).where(Meeting.tenant_id == tenant_id, Meeting.ms_meeting_id == ms_meeting_id)
        )
    ).scalar_one_or_none()
    if meeting is None:
        meeting = Meeting(
            tenant_id=tenant_id,
            ms_meeting_id=ms_meeting_id,
            title=title,
            organizer_id=organizer_id,
            status=MeetingStatus.pending,
        )
        db.add(meeting)
        await db.flush()
    return meeting


async def _index_transcript_text(
    db: AsyncSession, *, meeting: Meeting, raw_vtt: str, source: TranscriptSource
) -> None:
    if meeting.status == MeetingStatus.ready:
        # Idempotent: this meeting was already indexed (e.g. the user re-submitted
        # the same Meeting ID). Re-indexing would violate the one-transcript-per-
        # meeting constraint and duplicate chunks, so this is a no-op.
        return

    meeting.status = MeetingStatus.indexing
    await db.flush()

    cues = parse_vtt(raw_vtt)
    if not cues:
        meeting.status = MeetingStatus.no_transcript
        await db.commit()
        return

    chunks = chunk_cues(cues)
    transcript = MeetingTranscript(meeting_id=meeting.id, source=source, raw_format="vtt", storage_ref=raw_vtt)
    db.add(transcript)
    await db.flush()

    vectors = get_embedding_provider().embed_texts([c.text for c in chunks])
    indexable = [
        IndexableChunk(
            id=f"{meeting.id}:{chunk.chunk_index}",
            tenant_id=meeting.tenant_id,
            meeting_id=meeting.id,
            meeting_join_id=meeting.ms_meeting_id,
            meeting_title=meeting.title,
            speaker_name=chunk.speaker,
            start_time=chunk.start_seconds,
            end_time=chunk.end_seconds,
            content=chunk.text,
            chunk_index=chunk.chunk_index,
            source=source.value,
            document_id=transcript.id,
            embedding=vector,
        )
        for chunk, vector in zip(chunks, vectors)
    ]
    await get_search_provider().index_chunks(indexable)

    speakers = {c.speaker for c in cues if c.speaker}
    existing = {
        p.display_name
        for p in (
            await db.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting.id))
        ).scalars()
    }
    for speaker in speakers - existing:
        db.add(MeetingParticipant(meeting_id=meeting.id, display_name=speaker, role=ParticipantRole.attendee))

    meeting.transcript_available = True
    meeting.duration_seconds = int(max((c.end_seconds for c in cues), default=0))
    meeting.status = MeetingStatus.ready
    await db.commit()


async def load_meeting_from_graph(db: AsyncSession, *, user: User, join_meeting_id: str) -> Meeting:
    """Look up + index a meeting via Microsoft Graph. Requires the caller's
    Entra ID object id to be known (i.e. `AUTH_PROVIDER=entra`)."""
    if not user.ms_object_id:
        raise GraphNotConfiguredError(
            "Graph-backed meeting lookup requires signing in with Microsoft Entra ID."
        )

    client = get_graph_client()
    graph_meeting = await client.find_online_meeting(
        organizer_user_id=user.ms_object_id, join_meeting_id=join_meeting_id
    )

    meeting = await _get_or_create_meeting(
        db,
        tenant_id=user.tenant_id,
        ms_meeting_id=join_meeting_id,
        title=graph_meeting.get("subject", "Teams meeting"),
        organizer_id=user.id,
    )

    attendance = await client.get_attendance_report(
        organizer_user_id=user.ms_object_id, online_meeting_id=graph_meeting["id"]
    )
    for record in attendance:
        identity = record.get("identity", {})
        db.add(
            MeetingParticipant(
                meeting_id=meeting.id,
                display_name=identity.get("displayName", "Unknown"),
                email=identity.get("userIdentityType") and identity.get("id"),
                role=ParticipantRole.attendee,
            )
        )
    await db.flush()

    try:
        transcripts = await client.get_transcripts(
            organizer_user_id=user.ms_object_id, online_meeting_id=graph_meeting["id"]
        )
    except GraphMeetingNotFoundError:
        transcripts = []

    if not transcripts:
        meeting.status = MeetingStatus.no_transcript
        await db.commit()
        return meeting

    vtt = await client.get_transcript_content_vtt(
        organizer_user_id=user.ms_object_id,
        online_meeting_id=graph_meeting["id"],
        transcript_id=transcripts[0]["id"],
    )
    await _index_transcript_text(db, meeting=meeting, raw_vtt=vtt, source=TranscriptSource.graph)
    return meeting


async def load_meeting_manual(
    db: AsyncSession,
    *,
    user: User,
    meeting_id: str,
    title: str,
    raw_vtt: str,
) -> Meeting:
    """Manual-upload ingestion path (see module docstring)."""
    meeting = await _get_or_create_meeting(
        db, tenant_id=user.tenant_id, ms_meeting_id=meeting_id, title=title, organizer_id=user.id
    )
    existing_participant = (
        await db.execute(
            select(MeetingParticipant).where(
                MeetingParticipant.meeting_id == meeting.id, MeetingParticipant.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if existing_participant is None:
        db.add(
            MeetingParticipant(
                meeting_id=meeting.id,
                user_id=user.id,
                display_name=user.display_name,
                email=user.email,
                role=ParticipantRole.organizer,
            )
        )
    await db.flush()
    await _index_transcript_text(db, meeting=meeting, raw_vtt=raw_vtt, source=TranscriptSource.manual_upload)
    return meeting
