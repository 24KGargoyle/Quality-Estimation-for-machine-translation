from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.agents.meeting_router import extract_speaker_filter, is_cross_meeting_query
from meeting_intel.db.models import Meeting, MeetingParticipant, User
from meeting_intel.retrieval.hybrid_search import RetrievedChunk, hybrid_search
from meeting_intel.security.authz import get_all_authorized_meeting_ids


async def resolve_scope_and_retrieve(
    db: AsyncSession, *, meeting: Meeting, user: User, question: str
) -> tuple[list[RetrievedChunk], str | None, bool]:
    """Returns (retrieved_chunks, speaker_filter_used, cross_meeting_used)."""
    participants = (
        await db.execute(select(MeetingParticipant.display_name).where(MeetingParticipant.meeting_id == meeting.id))
    ).scalars().all()
    speaker = extract_speaker_filter(question, list(participants))

    cross_meeting = is_cross_meeting_query(question)
    meeting_ids = [meeting.id]
    if cross_meeting:
        authorized = await get_all_authorized_meeting_ids(db, user=user)
        # current meeting always included even if somehow missing from the authorized set
        meeting_ids = list({*authorized, meeting.id})

    chunks = await hybrid_search(
        db, tenant_id=user.tenant_id, meeting_ids=meeting_ids, query=question, speaker=speaker
    )
    return chunks, speaker, cross_meeting
