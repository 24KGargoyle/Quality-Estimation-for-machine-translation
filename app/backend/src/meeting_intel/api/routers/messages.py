from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.api.schemas import FeedbackRequest, ShareToGroupRequest
from meeting_intel.auth.deps import RequestContext, get_current_context
from meeting_intel.conversations.provider import get_provider
from meeting_intel.db.models import (
    AIResponse,
    AISource,
    Discussion,
    Feedback,
    FeedbackReason,
    FeedbackRating,
    Meeting,
    Message,
    MessageRole,
)
from meeting_intel.db.session import get_db
from meeting_intel.db.models import UserRole
from meeting_intel.security.authz import audit, get_authorized_group

router = APIRouter(prefix="/api/messages", tags=["messages"])
feedback_router = APIRouter(prefix="/api/feedback", tags=["feedback"])


@feedback_router.get("")
async def list_feedback(
    ctx: RequestContext = Depends(get_current_context), db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Feedback rows for evaluation (docs/FEEDBACK_AND_EVALUATION.md). Tenant
    admins see all tenant feedback; other users see only their own submissions."""
    stmt = select(Feedback).join(Message, Message.id == Feedback.message_id)
    if ctx.user.role != UserRole.admin:
        stmt = stmt.where(Feedback.user_id == ctx.user.id)
    else:
        from meeting_intel.db.models import Meeting

        stmt = stmt.where(
            (Feedback.meeting_id.is_(None))
            | (Feedback.meeting_id.in_(select(Meeting.id).where(Meeting.tenant_id == ctx.tenant_id)))
        )
    rows = (await db.execute(stmt.order_by(Feedback.created_at.desc()).limit(200))).scalars().all()
    return [
        {
            "id": f.id,
            "message_id": f.message_id,
            "meeting_id": f.meeting_id,
            "rating": f.rating.value,
            "reason": f.reason.value if f.reason else None,
            "comment": f.comment,
            "question": f.question,
            "answer": f.answer,
            "created_at": f.created_at.isoformat(),
        }
        for f in rows
    ]


def _fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


@router.post("/{message_id}/share")
async def share_message(
    message_id: str,
    payload: ShareToGroupRequest,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    message = (await db.execute(select(Message).where(Message.id == message_id))).scalar_one_or_none()
    if message is None or message.role != MessageRole.assistant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI message not found")

    from meeting_intel.security.authz import get_authorized_conversation

    if message.conversation_id:
        conversation = await get_authorized_conversation(
            db, user=ctx.user, conversation_id=message.conversation_id
        )
        if conversation.user_id != ctx.user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your message")

    group = await get_authorized_group(db, user=ctx.user, group_id=payload.group_id)

    meeting = None
    if message.meeting_id:
        meeting = (await db.execute(select(Meeting).where(Meeting.id == message.meeting_id))).scalar_one_or_none()

    ai_response = (await db.execute(select(AIResponse).where(AIResponse.message_id == message.id))).scalar_one_or_none()
    sources = []
    if ai_response:
        sources = (
            await db.execute(select(AISource).where(AISource.ai_response_id == ai_response.id))
        ).scalars().all()

    # Find the preceding user question for context, without pulling in the whole transcript.
    question = None
    if message.conversation_id:
        prior = (
            await db.execute(
                select(Message)
                .where(
                    Message.conversation_id == message.conversation_id,
                    Message.role == MessageRole.user,
                    Message.created_at < message.created_at,
                )
                .order_by(Message.created_at.desc())
            )
        ).scalars().first()
        question = prior.content if prior else None

    topic = payload.topic or (question or "Meeting context")
    card_lines = ["🤖 Meeting Copilot", ""]
    if meeting:
        card_lines += [f"Meeting: {meeting.title}", ""]
    card_lines += [f"Topic: {topic}", ""]
    if sources:
        s = sources[0]
        card_lines += [f"{s.speaker or 'Unknown'} — {_fmt_ts(s.start_seconds)}", "", s.excerpt, ""]
    if question:
        card_lines += [f"Question: {question}", ""]
    card_lines += [message.content, "", "Source: Meeting transcript"]
    card_text = "\n".join(card_lines)

    discussion = Discussion(
        group_id=group.id,
        meeting_id=meeting.id if meeting else None,
        shared_message_id=message.id,
        topic=topic,
        created_by=ctx.user.id,
    )
    db.add(discussion)
    await db.flush()

    shared_message = Message(
        group_id=group.id,
        sender_user_id=ctx.user.id,
        role=MessageRole.user,
        content=card_text,
        shared_from_message_id=message.id,
        meeting_id=meeting.id if meeting else None,
    )
    db.add(shared_message)
    await db.flush()

    provider = await get_provider(db, group_id=group.id)
    await provider.broadcast(
        group.id,
        {"id": shared_message.id, "sender_name": ctx.user.display_name, "content": card_text},
    )
    await provider.post_shared_context(group.id, html_content=card_text.replace("\n", "<br/>"))

    await audit(
        db, tenant_id=ctx.tenant_id, user_id=ctx.user.id, action="message.share", resource_type="message",
        resource_id=message.id, request_id=ctx.request_id, extra={"group_id": group.id},
    )
    await db.commit()
    return {"discussion_id": discussion.id, "group_id": group.id, "shared_message_id": shared_message.id}


@router.post("/{message_id}/feedback")
async def submit_feedback(
    message_id: str,
    payload: FeedbackRequest,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    message = (await db.execute(select(Message).where(Message.id == message_id))).scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    ai_response = (
        await db.execute(select(AIResponse).where(AIResponse.message_id == message.id))
    ).scalar_one_or_none()
    sources = []
    question = None
    if ai_response:
        source_rows = (
            await db.execute(select(AISource).where(AISource.ai_response_id == ai_response.id))
        ).scalars().all()
        sources = [s.id for s in source_rows]
        if message.conversation_id:
            prior = (
                await db.execute(
                    select(Message)
                    .where(
                        Message.conversation_id == message.conversation_id,
                        Message.role == MessageRole.user,
                        Message.created_at < message.created_at,
                    )
                    .order_by(Message.created_at.desc())
                )
            ).scalars().first()
            question = prior.content if prior else None

    reason = FeedbackReason(payload.reason) if payload.reason else None
    existing = (
        await db.execute(
            select(Feedback).where(Feedback.message_id == message.id, Feedback.user_id == ctx.user.id)
        )
    ).scalar_one_or_none()
    if existing:
        existing.rating = FeedbackRating(payload.rating)
        existing.reason = reason
        existing.comment = payload.comment
    else:
        db.add(
            Feedback(
                message_id=message.id,
                user_id=ctx.user.id,
                meeting_id=message.meeting_id,
                rating=FeedbackRating(payload.rating),
                reason=reason,
                comment=payload.comment,
                question=question,
                answer=message.content,
                retrieved_source_ids=sources,
            )
        )

    await audit(
        db, tenant_id=ctx.tenant_id, user_id=ctx.user.id, action="message.feedback", resource_type="message",
        resource_id=message.id, request_id=ctx.request_id, extra={"rating": payload.rating},
    )
    await db.commit()
    return {"status": "ok"}
