"""Server-side authorization checks.

Every meeting/group/conversation lookup goes through these helpers. Knowing a
Meeting ID (or group/conversation id) is never sufficient — the caller must
belong to the same tenant AND (for meetings) be a participant/organizer or a
tenant admin.
"""
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.db.models import (
    AuditLog,
    Conversation,
    Group,
    GroupMember,
    Meeting,
    MeetingParticipant,
    User,
    UserRole,
)


async def audit(
    db: AsyncSession,
    *,
    tenant_id: str,
    user_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    request_id: str | None = None,
    extra: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
            extra=extra,
        )
    )


async def get_authorized_meeting(db: AsyncSession, *, user: User, meeting_id: str) -> Meeting:
    meeting = (
        await db.execute(select(Meeting).where(Meeting.id == meeting_id, Meeting.tenant_id == user.tenant_id))
    ).scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")

    if user.role == UserRole.admin or meeting.organizer_id == user.id:
        return meeting

    is_participant = (
        await db.execute(
            select(MeetingParticipant.id).where(
                MeetingParticipant.meeting_id == meeting.id, MeetingParticipant.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if is_participant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this meeting",
        )
    return meeting


async def get_all_authorized_meeting_ids(db: AsyncSession, *, user: User) -> list[str]:
    """All meeting ids in the user's tenant that they are authorized to see.

    Used only for explicit cross-meeting queries (see agents/meeting_router.py)
    — never as the default search scope.
    """
    if user.role == UserRole.admin:
        rows = await db.execute(select(Meeting.id).where(Meeting.tenant_id == user.tenant_id))
        return [r[0] for r in rows.all()]

    organized = await db.execute(
        select(Meeting.id).where(Meeting.tenant_id == user.tenant_id, Meeting.organizer_id == user.id)
    )
    participated = await db.execute(
        select(MeetingParticipant.meeting_id).where(MeetingParticipant.user_id == user.id)
    )
    ids = {r[0] for r in organized.all()} | {r[0] for r in participated.all()}
    return list(ids)


async def get_authorized_group(db: AsyncSession, *, user: User, group_id: str) -> Group:
    group = (
        await db.execute(select(Group).where(Group.id == group_id, Group.tenant_id == user.tenant_id))
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")

    is_member = (
        await db.execute(
            select(GroupMember.id).where(GroupMember.group_id == group.id, GroupMember.user_id == user.id)
        )
    ).scalar_one_or_none()
    if is_member is None and user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not a member of this group")
    return group


async def get_authorized_conversation(db: AsyncSession, *, user: User, conversation_id: str) -> Conversation:
    conversation = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == user.tenant_id,
                Conversation.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation
