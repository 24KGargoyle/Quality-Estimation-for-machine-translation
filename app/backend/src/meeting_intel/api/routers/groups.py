from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.agents.discussion_agent import assist_discussion
from meeting_intel.api.schemas import GroupCreateRequest, GroupMessageRequest, GroupMessageSchema, GroupSummary
from meeting_intel.api.schemas import GroupAddMemberRequest, GroupMembersResponse, GroupMemberSchema
from meeting_intel.auth.deps import RequestContext, get_current_context
from meeting_intel.conversations.provider import get_provider
from meeting_intel.db.models import Group, GroupMember, Meeting, Message, MessageRole, User, UserRole
from meeting_intel.db.session import SessionLocal, get_db
from meeting_intel.security.authz import audit, get_authorized_group
from meeting_intel.security.jwt import InvalidTokenError, decode_session_token

router = APIRouter(prefix="/api/groups", tags=["groups"])


@router.post("", response_model=GroupSummary)
async def create_group(
    payload: GroupCreateRequest,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> GroupSummary:
    group = Group(tenant_id=ctx.tenant_id, name=payload.name, created_by=ctx.user.id)
    db.add(group)
    await db.flush()
    db.add(GroupMember(group_id=group.id, user_id=ctx.user.id))
    member_ids = {u for u in payload.member_user_ids if u != ctx.user.id}
    for uid in member_ids:
        member = (
            await db.execute(select(User).where(User.id == uid, User.tenant_id == ctx.tenant_id))
        ).scalar_one_or_none()
        if member:
            db.add(GroupMember(group_id=group.id, user_id=uid))
    await audit(
        db, tenant_id=ctx.tenant_id, user_id=ctx.user.id, action="group.create", resource_type="group",
        resource_id=group.id, request_id=ctx.request_id,
    )
    await db.commit()
    return GroupSummary(id=group.id, name=group.name, member_count=len(member_ids) + 1)


@router.get("", response_model=list[GroupSummary])
async def list_groups(
    ctx: RequestContext = Depends(get_current_context), db: AsyncSession = Depends(get_db)
) -> list[GroupSummary]:
    memberships = (
        await db.execute(select(GroupMember.group_id).where(GroupMember.user_id == ctx.user.id))
    ).scalars().all()
    if not memberships:
        return []
    groups = (await db.execute(select(Group).where(Group.id.in_(memberships)))).scalars().all()
    results = []
    for g in groups:
        count = len(
            (await db.execute(select(GroupMember).where(GroupMember.group_id == g.id))).scalars().all()
        )
        results.append(GroupSummary(id=g.id, name=g.name, member_count=count))
    return results


@router.get("/{group_id}/members", response_model=GroupMembersResponse)
async def list_group_members(
    group_id: str, ctx: RequestContext = Depends(get_current_context), db: AsyncSession = Depends(get_db),
) -> GroupMembersResponse:
    group = await get_authorized_group(db, user=ctx.user, group_id=group_id)
    users = (await db.execute(
        select(User).join(GroupMember, GroupMember.user_id == User.id).where(
            GroupMember.group_id == group.id, User.tenant_id == ctx.tenant_id,
        ).order_by(User.display_name, User.email)
    )).scalars().all()
    return GroupMembersResponse(
        members=[GroupMemberSchema(id=u.id, display_name=u.display_name, email=u.email) for u in users],
        can_manage=group.created_by == ctx.user.id or ctx.user.role == UserRole.admin,
    )


@router.post("/{group_id}/members", response_model=GroupMembersResponse)
async def add_group_member(
    group_id: str, payload: GroupAddMemberRequest,
    ctx: RequestContext = Depends(get_current_context), db: AsyncSession = Depends(get_db),
) -> GroupMembersResponse:
    group = await get_authorized_group(db, user=ctx.user, group_id=group_id)
    if group.created_by != ctx.user.id and ctx.user.role != UserRole.admin:
        raise HTTPException(403, "Only the group creator or an administrator can add members")
    member = (await db.execute(select(User).where(
        User.tenant_id == ctx.tenant_id, func.lower(User.email) == payload.email.strip().lower(),
    ))).scalars().first()
    if member is None:
        raise HTTPException(404, "No registered user with that email in your organization. They must sign in first.")
    existing = (await db.execute(select(GroupMember.id).where(
        GroupMember.group_id == group.id, GroupMember.user_id == member.id,
    ))).scalar_one_or_none()
    if existing is None:
        db.add(GroupMember(group_id=group.id, user_id=member.id))
        await audit(db, tenant_id=ctx.tenant_id, user_id=ctx.user.id, action="group.member.add",
                    resource_type="group", resource_id=group.id, request_id=ctx.request_id,
                    extra={"member_user_id": member.id})
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(409, "Membership changed. Refresh the member list and try again.") from None
    return await list_group_members(group_id, ctx, db)


@router.get("/{group_id}/messages", response_model=list[GroupMessageSchema])
async def list_group_messages(
    group_id: str,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> list[GroupMessageSchema]:
    group = await get_authorized_group(db, user=ctx.user, group_id=group_id)
    messages = (
        await db.execute(select(Message).where(Message.group_id == group.id).order_by(Message.created_at))
    ).scalars().all()
    return [await _to_group_message_schema(db, m) for m in messages]


async def _to_group_message_schema(db: AsyncSession, m: Message) -> GroupMessageSchema:
    sender_name = "Meeting Copilot"
    if m.sender_user_id:
        user = (await db.execute(select(User).where(User.id == m.sender_user_id))).scalar_one_or_none()
        sender_name = user.display_name if user else "Unknown"
    return GroupMessageSchema(
        id=m.id, sender_user_id=m.sender_user_id, sender_name=sender_name, content=m.content, created_at=m.created_at
    )


@router.post("/{group_id}/messages", response_model=list[GroupMessageSchema])
async def post_group_message(
    group_id: str,
    payload: GroupMessageRequest,
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> list[GroupMessageSchema]:
    group = await get_authorized_group(db, user=ctx.user, group_id=group_id)
    provider = await get_provider(db, group_id=group.id)

    user_message = Message(
        group_id=group.id, sender_user_id=ctx.user.id, role=MessageRole.user, content=payload.content
    )
    db.add(user_message)
    await db.flush()
    out_schemas = [await _to_group_message_schema(db, user_message)]
    await provider.broadcast(group.id, out_schemas[0].model_dump(mode="json"))

    if payload.ask_ai:
        history_rows = (
            await db.execute(select(Message).where(Message.group_id == group.id).order_by(Message.created_at))
        ).scalars().all()
        history = [
            {"sender": (await _to_group_message_schema(db, m)).sender_name, "content": m.content}
            for m in history_rows
        ]
        # Use the meeting linked to this group's most recent discussion, if any.
        from meeting_intel.db.models import Discussion

        latest_discussion = (
            await db.execute(
                select(Discussion).where(Discussion.group_id == group.id).order_by(Discussion.created_at.desc())
            )
        ).scalars().first()
        meeting = None
        if latest_discussion and latest_discussion.meeting_id:
            meeting = (
                await db.execute(select(Meeting).where(Meeting.id == latest_discussion.meeting_id))
            ).scalar_one_or_none()

        answer_text = await assist_discussion(
            db, meeting=meeting, group_history=history, question=payload.content
        )
        ai_message = Message(group_id=group.id, sender_user_id=None, role=MessageRole.assistant, content=answer_text)
        db.add(ai_message)
        await db.flush()
        ai_schema = await _to_group_message_schema(db, ai_message)
        out_schemas.append(ai_schema)
        await provider.broadcast(group.id, ai_schema.model_dump(mode="json"))

    await audit(
        db, tenant_id=ctx.tenant_id, user_id=ctx.user.id, action="group.message", resource_type="group",
        resource_id=group.id, request_id=ctx.request_id,
    )
    await db.commit()
    return out_schemas


@router.websocket("/{group_id}/ws")
async def group_ws(websocket: WebSocket, group_id: str, token: str) -> None:
    from meeting_intel.realtime.ws_manager import ws_manager

    try:
        claims = decode_session_token(token)
    except InvalidTokenError:
        await websocket.close(code=4401)
        return

    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.id == claims["sub"]))).scalar_one_or_none()
        if user is None:
            await websocket.close(code=4401)
            return
        member = (
            await db.execute(
                select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user.id)
            )
        ).scalar_one_or_none()
        if member is None:
            await websocket.close(code=4403)
            return

    await ws_manager.connect(group_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # keepalive / ignored; writes go through the REST endpoint
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(group_id, websocket)
