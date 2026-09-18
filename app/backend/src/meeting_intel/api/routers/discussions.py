from html import escape
import httpx
from meeting_intel.graph.client import GraphNotConfiguredError, GraphMeetingNotFoundError, GraphTransientError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.agents.decision_agent import detect_decision
from meeting_intel.api.schemas import (
    ActionItemSchema,
    CreateTeamsGroupRequest,
    CreateTeamsGroupResponse,
    DecisionConfirmRequest,
    DecisionSchema,
    DiscussionSummary,
    FindTeamsGroupRequest,
    FindTeamsGroupResponse,
    MatchedChatSchema,
    ResolvedParticipantSchema,
    SendTeamsDiscussionRequest,
    SendTeamsDiscussionResponse,
)
from meeting_intel.auth.deps import RequestContext, get_current_context
from meeting_intel.config import get_settings
from meeting_intel.db.models import (
    AIResponse, AISource, Conversation,
    ActionItem,
    ActionItemSource,
    Decision,
    DecisionStatus,
    Discussion,
    Group,
    GroupMember,
    Message,
    MessageRole,
    TeamsMapping,
    User,
)
from meeting_intel.db.session import get_db
from meeting_intel.graph.delegated_auth import DelegatedTokenUnavailableError, get_valid_delegated_token
from meeting_intel.realtime.ws_manager import ws_manager
from meeting_intel.security.authz import audit, get_authorized_group, get_authorized_meeting
from meeting_intel.teams.group_matcher import find_matching_chat
from meeting_intel.teams.participant_resolver import MeetingParticipantResolver

router = APIRouter(prefix="/api/discussions", tags=["discussions"])
settings = get_settings()


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
    if payload.meeting_id:
        await get_authorized_meeting(db, user=ctx.user, meeting_id=payload.meeting_id)
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


# --------------------------------------------------------------------------
# Discuss with Group v2 — Teams participant/group resolution (Parts 4-10).
#
# The "agentic workflow" (§10): resolve meeting participants -> find an
# existing Teams group chat matching them -> if none, let the user create
# one -> bind it to an application Group (existing Groups functionality is
# reused, never duplicated — §11) -> send a concise, grounded discussion
# message. Every step here uses the signed-in user's own delegated Graph
# token (§14), never app-only access, and every id from the frontend is
# re-validated against server-resolved data before being trusted (§12).
# --------------------------------------------------------------------------


def teams_errors(handler):
    from functools import wraps
    @wraps(handler)
    async def guarded(*args, **kwargs):
        try:
            return await handler(*args, **kwargs)
        except (GraphNotConfiguredError, GraphMeetingNotFoundError, GraphTransientError, httpx.HTTPError):
            raise HTTPException(503, "Microsoft Teams is unavailable or permission was denied. No successful operation could be confirmed; check Teams before retrying.") from None
    return guarded


def _resolved_to_schema(p) -> ResolvedParticipantSchema:
    return ResolvedParticipantSchema(
        display_name=p.display_name, user_id=p.user_id, email=p.email, role=p.role,
        source=p.source, resolved=p.resolved,
    )


async def _bind_teams_chat_to_group(
    db: AsyncSession, *, tenant_id: str, teams_chat_id: str, topic: str, creator_id: str
) -> str:
    """Returns the application Group id bound to this Teams chat,
    creating the Group + TeamsMapping if this chat has never been seen by
    the app before (§11: an application Group and a Teams chat are related
    but distinct — this is the one place that relationship is created)."""
    existing = (
        await db.execute(select(TeamsMapping).where(TeamsMapping.teams_chat_id == teams_chat_id, TeamsMapping.tenant_id == tenant_id))
    ).scalar_one_or_none()
    if existing and existing.group_id:
        return existing.group_id

    group = Group(tenant_id=tenant_id, name=topic, created_by=creator_id)
    db.add(group)
    await db.flush()
    db.add(GroupMember(group_id=group.id, user_id=creator_id))
    db.add(TeamsMapping(tenant_id=tenant_id, group_id=group.id, teams_chat_id=teams_chat_id))
    await db.flush()
    return group.id


@router.post("/find-teams-group", response_model=FindTeamsGroupResponse)
@teams_errors
async def find_teams_group(
    payload: FindTeamsGroupRequest,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> FindTeamsGroupResponse:
    meeting = await get_authorized_meeting(db, user=ctx.user, meeting_id=payload.meeting_id)
    try:
        resolved = await MeetingParticipantResolver().resolve(db, meeting=meeting)
    except (GraphNotConfiguredError, GraphMeetingNotFoundError, GraphTransientError, httpx.HTTPError):
        raise HTTPException(503, "Teams attendance is unavailable. Check Graph permissions and try again.") from None
    participants_schema = [_resolved_to_schema(p) for p in resolved]

    if not settings.graph_configured:
        return FindTeamsGroupResponse(
            teams_available=False,
            unavailable_reason="Microsoft Teams participant/group integration is not configured.",
            participants=participants_schema,
        )

    try:
        token = await get_valid_delegated_token(db, user=ctx.user)
    except DelegatedTokenUnavailableError as exc:
        return FindTeamsGroupResponse(teams_available=False, unavailable_reason=str(exc), participants=participants_schema)

    from meeting_intel.graph.client import get_graph_client

    target_ids = {p.user_id for p in resolved if p.resolved and p.user_id}
    chats = await get_graph_client().list_my_group_chats(token)
    target_ids.add(ctx.user.ms_object_id)
    match = find_matching_chat(chats, target_ids) if resolved and all(p.resolved for p in resolved) else None

    existing_group_id = None
    matched_schema = None
    if match:
        matched_schema = MatchedChatSchema(
            chat_id=match.chat_id, topic=match.topic, member_names=match.member_names, member_ids=sorted(target_ids), match_kind=match.match_kind
        )
        existing_group_id = await _bind_teams_chat_to_group(
            db, tenant_id=ctx.tenant_id, teams_chat_id=match.chat_id,
            topic=match.topic or meeting.title, creator_id=ctx.user.id,
        )

    await audit(
        db, tenant_id=ctx.tenant_id, user_id=ctx.user.id, action="teams_group.find", resource_type="meeting",
        resource_id=meeting.id, request_id=ctx.request_id, extra={"found": match is not None},
    )
    await db.commit()
    return FindTeamsGroupResponse(
        teams_available=True, participants=participants_schema, existing_group=matched_schema,
        application_group_id=existing_group_id,
    )


@router.post("/create-teams-group", response_model=CreateTeamsGroupResponse)
@teams_errors
async def create_teams_group(
    payload: CreateTeamsGroupRequest,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> CreateTeamsGroupResponse:
    meeting = await get_authorized_meeting(db, user=ctx.user, meeting_id=payload.meeting_id)
    try:
        resolved = await MeetingParticipantResolver().resolve(db, meeting=meeting)
    except (GraphNotConfiguredError, GraphMeetingNotFoundError, GraphTransientError, httpx.HTTPError):
        raise HTTPException(503, "Teams attendance is unavailable. Check Graph permissions and try again.") from None
    authorized_ids = {p.user_id for p in resolved if p.resolved and p.user_id}

    requested = set(payload.participant_user_ids)
    if not requested or not requested.issubset(authorized_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more participant ids are not authorized, resolved participants of this meeting.",
        )

    if not settings.graph_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft Teams participant/group integration is not configured.",
        )
    try:
        token = await get_valid_delegated_token(db, user=ctx.user)
    except DelegatedTokenUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    from meeting_intel.graph.client import get_graph_client

    requested.add(ctx.user.ms_object_id)
    if len(requested) < 2:
        raise HTTPException(400, "Select at least one other resolved participant.")
    topic = payload.topic.strip() or f"Meeting Copilot — {meeting.title}"
    chat = await get_graph_client().create_group_chat(token, member_user_ids=list(requested), topic=topic)
    teams_chat_id = chat["id"]

    group = Group(tenant_id=ctx.tenant_id, name=topic, created_by=ctx.user.id)
    db.add(group)
    await db.flush()
    db.add(GroupMember(group_id=group.id, user_id=ctx.user.id))
    member_names = [ctx.user.display_name]
    for p in resolved:
        if p.user_id in requested:
            local_user = (
                await db.execute(
                    select(User).where(User.tenant_id == ctx.tenant_id, User.ms_object_id == p.user_id)
                )
            ).scalar_one_or_none()
            if local_user and local_user.id != ctx.user.id:
                db.add(GroupMember(group_id=group.id, user_id=local_user.id))
            member_names.append(p.display_name)
    db.add(TeamsMapping(tenant_id=ctx.tenant_id, group_id=group.id, teams_chat_id=teams_chat_id))

    await audit(
        db, tenant_id=ctx.tenant_id, user_id=ctx.user.id, action="teams_group.create", resource_type="group",
        resource_id=group.id, request_id=ctx.request_id, extra={"teams_chat_id": teams_chat_id},
    )
    await db.commit()
    return CreateTeamsGroupResponse(
        application_group_id=group.id, teams_chat_id=teams_chat_id, topic=topic, member_names=member_names, member_ids=sorted(requested)
    )


@router.post("/send-teams-discussion", response_model=SendTeamsDiscussionResponse)
@teams_errors
async def send_teams_discussion(
    payload: SendTeamsDiscussionRequest,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> SendTeamsDiscussionResponse:
    meeting = await get_authorized_meeting(db, user=ctx.user, meeting_id=payload.meeting_id)
    group = await get_authorized_group(db, user=ctx.user, group_id=payload.group_id)

    mapping = (await db.execute(select(TeamsMapping).where(TeamsMapping.group_id == group.id, TeamsMapping.tenant_id == ctx.tenant_id))).scalar_one_or_none()
    if not mapping or not mapping.teams_chat_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This group is not linked to a Microsoft Teams chat.")

    if not settings.graph_configured:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Microsoft Teams integration is not configured.")
    try:
        token = await get_valid_delegated_token(db, user=ctx.user)
    except DelegatedTokenUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    from meeting_intel.graph.client import get_graph_client

    # Re-validate server-side, right before sending, that the caller is
    # still actually a member of this Teams chat — a chat_id resolved
    # earlier in the session (or an application group_id guessed/reused)
    # is never sufficient authorization on its own.
    members = await get_graph_client().get_chat_members(token, chat_id=mapping.teams_chat_id)
    member_ids = {m.get("userId") for m in members if m.get("userId")}
    if not ctx.user.ms_object_id or ctx.user.ms_object_id not in member_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this Teams chat.")

    if len(member_ids) != len(members) or member_ids != set(payload.recipient_user_ids):
        raise HTTPException(409, "Chat membership changed. Review the recipients again before sending.")
    resolved = await MeetingParticipantResolver().resolve(db, meeting=meeting)
    allowed = {p.user_id for p in resolved if p.resolved and p.user_id} | {ctx.user.ms_object_id}
    if not member_ids.issubset(allowed):
        raise HTTPException(403, "Chat contains recipients not resolved for this meeting.")

    message = (await db.execute(select(Message).join(Conversation, Message.conversation_id == Conversation.id).where(
        Message.id == payload.message_id, Message.meeting_id == meeting.id,
        Message.role == MessageRole.assistant, Conversation.user_id == ctx.user.id,
        Conversation.tenant_id == ctx.tenant_id, Conversation.meeting_id == meeting.id,
    ))).scalar_one_or_none()
    if message is None:
        raise HTTPException(404, "Answer not found in your meeting conversation.")
    sources = (await db.execute(select(AISource).join(AIResponse, AISource.ai_response_id == AIResponse.id)
        .where(AIResponse.message_id == message.id))).scalars().all()
    card_lines = ["Meeting Copilot", f"Meeting: {meeting.title}", f"Topic: {payload.topic}", "", message.content[:4000]]
    for source in sources[:3]:
        card_lines += ["", f"Source: {source.source_file or 'Meeting transcript'}", source.excerpt[:1500]]
    card_lines += ["", f"Discussion question: {payload.question[:1000]}"]
    card_text = "\n".join(card_lines)

    await get_graph_client().send_chat_message_delegated(
        token, chat_id=mapping.teams_chat_id, content_html=escape(card_text).replace("\n", "<br/>")
    )

    discussion = Discussion(group_id=group.id, meeting_id=meeting.id, topic=payload.topic, created_by=ctx.user.id)
    db.add(discussion)
    await db.flush()
    shared_message = Message(
        group_id=group.id, sender_user_id=ctx.user.id, role=MessageRole.user, content=card_text, meeting_id=meeting.id
    )
    db.add(shared_message)
    await db.flush()

    await ws_manager.broadcast(
        group.id, {"id": shared_message.id, "sender_name": ctx.user.display_name, "content": card_text}
    )

    await audit(
        db, tenant_id=ctx.tenant_id, user_id=ctx.user.id, action="teams_discussion.send", resource_type="discussion",
        resource_id=discussion.id, request_id=ctx.request_id, extra={"teams_chat_id": mapping.teams_chat_id},
    )
    await db.commit()
    return SendTeamsDiscussionResponse(
        discussion_id=discussion.id, message_id=shared_message.id, teams_chat_id=mapping.teams_chat_id
    )
