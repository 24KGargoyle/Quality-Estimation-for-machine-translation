from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.agents.query_understanding import QueryUnderstanding, understand_query
from meeting_intel.db.models import Meeting, MeetingParticipant, User
from meeting_intel.retrieval.hybrid_search import RetrievedChunk, hybrid_search
from meeting_intel.security.authz import get_all_authorized_meeting_ids


async def resolve_scope_and_retrieve(
    db: AsyncSession, *, meeting: Meeting, user: User, question: str, document=None
) -> tuple[list[RetrievedChunk], QueryUnderstanding]:
    """Returns (retrieved_chunks, speaker_filter_used, cross_meeting_used)."""
    participants = (
        await db.execute(select(MeetingParticipant.display_name).where(MeetingParticipant.meeting_id == meeting.id))
    ).scalars().all()
    understanding = understand_query(question, list(participants))
    speaker = understanding.person

    cross_meeting = document is None and understanding.is_cross_meeting
    meeting_ids = [meeting.id]
    if cross_meeting:
        authorized = await get_all_authorized_meeting_ids(db, user=user)
        # current meeting always included even if somehow missing from the authorized set
        meeting_ids = list({*authorized, meeting.id})

    retrieval_query = question
    if re.fullmatch(r"\s*(?:participants?|attendees?|who attended|who participated)[?.!\s]*", question, re.I):
        retrieval_query = "Who participated in the meeting? People who spoke, demonstrated, asked questions, or received a walkthrough."
    chunks = await hybrid_search(
        db, tenant_id=user.tenant_id, meeting_ids=meeting_ids, query=retrieval_query, speaker=speaker if document is None or document.file_type == "vtt" else None,
        document_id=f"hist:{document.file_hash[:16]}" if document else None,
    )
    understanding.is_cross_meeting = cross_meeting
    return chunks, understanding
