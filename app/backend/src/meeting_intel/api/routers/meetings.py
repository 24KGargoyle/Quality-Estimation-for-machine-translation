from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.api.schemas import MeetingDetail, MeetingLoadRequest, MeetingSummary
from meeting_intel.auth.deps import RequestContext, get_current_context
from meeting_intel.auth.entra import GraphNotConfiguredError
from meeting_intel.db.models import Meeting, MeetingParticipant
from meeting_intel.db.session import get_db
from meeting_intel.ingestion.pipeline import load_meeting_from_graph, load_meeting_manual
from meeting_intel.security.authz import audit, get_authorized_meeting

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


async def _to_detail(db: AsyncSession, meeting: Meeting) -> MeetingDetail:
    participants = (
        await db.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting.id))
    ).scalars().all()
    return MeetingDetail(
        id=meeting.id,
        ms_meeting_id=meeting.ms_meeting_id,
        title=meeting.title,
        scheduled_start=meeting.scheduled_start,
        duration_seconds=meeting.duration_seconds,
        participant_count=len(participants),
        transcript_available=meeting.transcript_available,
        recording_available=meeting.recording_available,
        status=meeting.status.value,
        participants=[{"display_name": p.display_name, "role": p.role.value} for p in participants],
    )


@router.post("/load", response_model=MeetingDetail)
async def load_meeting(
    payload: MeetingLoadRequest,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> MeetingDetail:
    if payload.transcript_vtt:
        meeting = await load_meeting_manual(
            db,
            user=ctx.user,
            meeting_id=payload.meeting_id,
            title=payload.title or f"Meeting {payload.meeting_id}",
            raw_vtt=payload.transcript_vtt,
        )
    else:
        try:
            meeting = await load_meeting_from_graph(db, user=ctx.user, join_meeting_id=payload.meeting_id)
        except GraphNotConfiguredError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    await audit(
        db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user.id,
        action="meeting.load",
        resource_type="meeting",
        resource_id=meeting.id,
        request_id=ctx.request_id,
    )
    await db.commit()
    return await _to_detail(db, meeting)


@router.get("", response_model=list[MeetingSummary])
async def list_meetings(
    ctx: RequestContext = Depends(get_current_context), db: AsyncSession = Depends(get_db)
) -> list[MeetingSummary]:
    from meeting_intel.security.authz import get_all_authorized_meeting_ids

    ids = await get_all_authorized_meeting_ids(db, user=ctx.user)
    if not ids:
        return []
    meetings = (await db.execute(select(Meeting).where(Meeting.id.in_(ids)))).scalars().all()
    results = []
    for m in meetings:
        count = (
            await db.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == m.id))
        ).scalars().all()
        results.append(
            MeetingSummary(
                id=m.id,
                ms_meeting_id=m.ms_meeting_id,
                title=m.title,
                scheduled_start=m.scheduled_start,
                duration_seconds=m.duration_seconds,
                participant_count=len(count),
                transcript_available=m.transcript_available,
                recording_available=m.recording_available,
                status=m.status.value,
            )
        )
    return results


@router.get("/{meeting_id}", response_model=MeetingDetail)
async def get_meeting(
    meeting_id: str,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> MeetingDetail:
    meeting = await get_authorized_meeting(db, user=ctx.user, meeting_id=meeting_id)
    return await _to_detail(db, meeting)


@router.get("/{meeting_id}/search")
async def search_meeting(
    meeting_id: str,
    q: str,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Direct hybrid search (no LLM call) over a single meeting's transcript —
    powers the Search nav tab, separate from the grounded chat Q&A flow."""
    meeting = await get_authorized_meeting(db, user=ctx.user, meeting_id=meeting_id)
    from meeting_intel.retrieval.hybrid_search import hybrid_search

    results = await hybrid_search(db, meeting_ids=[meeting.id], query=q, top_k=15)
    return [
        {
            "chunk_id": r.chunk.id,
            "speaker": r.chunk.speaker,
            "start_seconds": r.chunk.start_seconds,
            "end_seconds": r.chunk.end_seconds,
            "text": r.chunk.text,
            "score": r.score,
        }
        for r in results
    ]


@router.get("/{meeting_id}/sources")
async def get_meeting_sources(
    meeting_id: str,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """All transcript chunks for a meeting the caller is authorized to see —
    used by the UI to show a raw source browser."""
    meeting = await get_authorized_meeting(db, user=ctx.user, meeting_id=meeting_id)
    from meeting_intel.db.models import TranscriptChunk

    chunks = (
        await db.execute(
            select(TranscriptChunk)
            .where(TranscriptChunk.meeting_id == meeting.id)
            .order_by(TranscriptChunk.chunk_index)
        )
    ).scalars().all()
    return [
        {
            "chunk_id": c.id,
            "speaker": c.speaker,
            "start_seconds": c.start_seconds,
            "end_seconds": c.end_seconds,
            "text": c.text,
        }
        for c in chunks
    ]
