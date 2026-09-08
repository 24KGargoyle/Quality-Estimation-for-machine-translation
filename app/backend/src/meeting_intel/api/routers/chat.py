from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.agents.answer_agent import answer_question
from meeting_intel.api.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationSummary,
    MessageSchema,
    SourceSchema,
)
from meeting_intel.auth.deps import RequestContext, get_current_context
from meeting_intel.db.models import (
    AIResponse,
    AISource,
    Conversation,
    ConversationKind,
    Message,
    MessageRole,
)
from meeting_intel.db.session import get_db
from meeting_intel.security.authz import audit, get_authorized_conversation, get_authorized_meeting

router = APIRouter(prefix="/api", tags=["chat"])


def _fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    meeting = await get_authorized_meeting(db, user=ctx.user, meeting_id=payload.meeting_id)

    if payload.conversation_id:
        conversation = await get_authorized_conversation(db, user=ctx.user, conversation_id=payload.conversation_id)
    else:
        conversation = Conversation(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user.id,
            meeting_id=meeting.id,
            kind=ConversationKind.private_meeting,
            title=meeting.title,
        )
        db.add(conversation)
        await db.flush()

    history_rows = (
        await db.execute(
            select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)
        )
    ).scalars().all()
    history = [{"role": m.role.value, "content": m.content} for m in history_rows]

    db.add(
        Message(
            conversation_id=conversation.id,
            sender_user_id=ctx.user.id,
            role=MessageRole.user,
            content=payload.message,
            meeting_id=meeting.id,
        )
    )
    await db.flush()

    result = await answer_question(db, meeting=meeting, user=ctx.user, history=history, question=payload.message)

    assistant_message = Message(
        conversation_id=conversation.id,
        sender_user_id=None,
        role=MessageRole.assistant,
        content=result.text,
        meeting_id=meeting.id,
    )
    db.add(assistant_message)
    await db.flush()

    ai_response = AIResponse(
        message_id=assistant_message.id,
        meeting_id=meeting.id,
        retrieval_query=result.retrieval_query,
        evidence_sufficient=result.evidence_sufficient,
        model=result.model or "n/a",
        latency_ms=result.latency_ms,
    )
    db.add(ai_response)
    await db.flush()

    sources_out = []
    for s in result.sources:
        db.add(
            AISource(
                ai_response_id=ai_response.id,
                chunk_id=s.chunk.id,
                speaker=s.speaker,
                start_seconds=s.start_seconds,
                end_seconds=s.end_seconds,
                excerpt=s.excerpt,
                score=s.score,
            )
        )
        sources_out.append(
            SourceSchema(
                speaker=s.speaker,
                start_timestamp=_fmt_ts(s.start_seconds),
                end_timestamp=_fmt_ts(s.end_seconds),
                excerpt=s.excerpt,
            )
        )

    await audit(
        db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user.id,
        action="chat.ask",
        resource_type="meeting",
        resource_id=meeting.id,
        request_id=ctx.request_id,
        extra={"evidence_sufficient": result.evidence_sufficient, "source_count": len(sources_out)},
    )
    await db.commit()

    return ChatResponse(
        conversation_id=conversation.id,
        message_id=assistant_message.id,
        answer=result.text,
        evidence_sufficient=result.evidence_sufficient,
        cross_meeting=result.cross_meeting,
        speaker_filter=result.speaker_filter,
        sources=sources_out,
    )


@router.get("/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    ctx: RequestContext = Depends(get_current_context), db: AsyncSession = Depends(get_db)
) -> list[ConversationSummary]:
    rows = (
        await db.execute(
            select(Conversation)
            .where(Conversation.user_id == ctx.user.id, Conversation.tenant_id == ctx.tenant_id)
            .order_by(Conversation.updated_at.desc())
        )
    ).scalars().all()
    return [ConversationSummary.model_validate(r) for r in rows]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetail:
    conversation = await get_authorized_conversation(db, user=ctx.user, conversation_id=conversation_id)
    messages = (
        await db.execute(
            select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)
        )
    ).scalars().all()

    message_schemas = []
    for m in messages:
        sources = []
        if m.role == MessageRole.assistant:
            ai_response = (
                await db.execute(select(AIResponse).where(AIResponse.message_id == m.id))
            ).scalar_one_or_none()
            if ai_response:
                src_rows = (
                    await db.execute(select(AISource).where(AISource.ai_response_id == ai_response.id))
                ).scalars().all()
                sources = [
                    SourceSchema(
                        speaker=s.speaker,
                        start_timestamp=_fmt_ts(s.start_seconds),
                        end_timestamp=_fmt_ts(s.end_seconds),
                        excerpt=s.excerpt,
                    )
                    for s in src_rows
                ]
        message_schemas.append(
            MessageSchema(
                id=m.id,
                role=m.role.value,
                content=m.content,
                sender_user_id=m.sender_user_id,
                created_at=m.created_at,
                sources=sources,
            )
        )

    return ConversationDetail(
        id=conversation.id,
        meeting_id=conversation.meeting_id,
        title=conversation.title,
        updated_at=conversation.updated_at,
        messages=message_schemas,
    )
