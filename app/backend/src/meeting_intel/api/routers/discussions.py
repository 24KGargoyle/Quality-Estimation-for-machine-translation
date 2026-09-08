from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.agents.decision_agent import detect_decision
from meeting_intel.api.schemas import ActionItemSchema, DecisionConfirmRequest, DecisionSchema, DiscussionSummary
from meeting_intel.auth.deps import RequestContext, get_current_context
from meeting_intel.db.models import (
    ActionItem,
    ActionItemSource,
    Decision,
    DecisionStatus,
    Discussion,
    Message,
)
from meeting_intel.db.session import get_db
from meeting_intel.security.authz import audit, get_authorized_group

router = APIRouter(prefix="/api/discussions", tags=["discussions"])


class CreateDiscussionRequest(BaseModel):
    group_id: str
    meeting_id: str | None = None
    topic: str


@router.post("", response_model=DiscussionSummary)
async def create_discussion(
    payload: CreateDiscussionRequest,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> DiscussionSummary:
    group = await get_authorized_group(db, user=ctx.user, group_id=payload.group_id)
    discussion = Discussion(
        group_id=group.id, meeting_id=payload.meeting_id, topic=payload.topic, created_by=ctx.user.id
    )
    db.add(discussion)
    await audit(
        db, tenant_id=ctx.tenant_id, user_id=ctx.user.id, action="discussion.create",
        resource_type="discussion", resource_id=discussion.id, request_id=ctx.request_id,
    )
    await db.commit()
    return DiscussionSummary.model_validate(discussion)


async def _group_history(db: AsyncSession, group_id: str) -> list[dict]:
    from meeting_intel.api.routers.groups import _to_group_message_schema

    rows = (
        await db.execute(select(Message).where(Message.group_id == group_id).order_by(Message.created_at))
    ).scalars().all()
    out = []
    for m in rows:
        schema = await _to_group_message_schema(db, m)
        out.append({"sender": schema.sender_name, "content": schema.content})
    return out


@router.get("/{discussion_id}/suggested-decision")
async def suggested_decision(
    discussion_id: str,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> dict:
    discussion = (
        await db.execute(select(Discussion).where(Discussion.id == discussion_id))
    ).scalar_one_or_none()
    if discussion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discussion not found")
    await get_authorized_group(db, user=ctx.user, group_id=discussion.group_id)

    history = await _group_history(db, discussion.group_id)
    suggestion = await detect_decision(history)
    return {
        "detected": suggestion.detected,
        "decision_text": suggestion.decision_text,
        "action_items": [{"task": a.task, "owner": a.owner} for a in suggestion.action_items],
    }


@router.post("/{discussion_id}/decisions", response_model=DecisionSchema)
async def confirm_decision(
    discussion_id: str,
    payload: DecisionConfirmRequest,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> DecisionSchema:
    """Human-confirmed decision capture. Never called automatically by the agent."""
    discussion = (
        await db.execute(select(Discussion).where(Discussion.id == discussion_id))
    ).scalar_one_or_none()
    if discussion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discussion not found")
    await get_authorized_group(db, user=ctx.user, group_id=discussion.group_id)

    from datetime import datetime, timezone

    decision = Decision(
        group_id=discussion.group_id,
        discussion_id=discussion.id,
        meeting_id=discussion.meeting_id,
        decision_text=payload.decision_text,
        status=DecisionStatus.confirmed,
        created_by=ctx.user.id,
        confirmed_at=datetime.now(timezone.utc),
    )
    db.add(decision)
    await db.flush()

    for item in payload.action_items:
        db.add(
            ActionItem(
                group_id=discussion.group_id,
                meeting_id=discussion.meeting_id,
                decision_id=decision.id,
                task=item.get("task", ""),
                owner_name=item.get("owner_name") or item.get("owner"),
                source=ActionItemSource.group_discussion,
            )
        )

    await audit(
        db, tenant_id=ctx.tenant_id, user_id=ctx.user.id, action="decision.confirm", resource_type="decision",
        resource_id=decision.id, request_id=ctx.request_id,
    )
    await db.commit()
    return DecisionSchema.model_validate(decision)


@router.get("/groups/{group_id}/decisions", response_model=list[DecisionSchema])
async def list_decisions(
    group_id: str, ctx: RequestContext = Depends(get_current_context), db: AsyncSession = Depends(get_db)
) -> list[DecisionSchema]:
    await get_authorized_group(db, user=ctx.user, group_id=group_id)
    rows = (await db.execute(select(Decision).where(Decision.group_id == group_id))).scalars().all()
    return [DecisionSchema.model_validate(r) for r in rows]


@router.get("/groups/{group_id}/action-items", response_model=list[ActionItemSchema])
async def list_action_items(
    group_id: str, ctx: RequestContext = Depends(get_current_context), db: AsyncSession = Depends(get_db)
) -> list[ActionItemSchema]:
    await get_authorized_group(db, user=ctx.user, group_id=group_id)
    rows = (
        await db.execute(select(ActionItem).where(ActionItem.group_id == group_id))
    ).scalars().all()
    return [ActionItemSchema.model_validate(r) for r in rows]
