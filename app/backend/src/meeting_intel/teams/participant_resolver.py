"""Resolve identities only from actual same-tenant Teams attendance records.
Historical transcript names are never mapped to identities by guessing.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.auth.entra import GraphNotConfiguredError
from meeting_intel.config import get_settings
from meeting_intel.db.models import Meeting, MeetingParticipant, User

settings = get_settings()


@dataclass
class ResolvedParticipant:
    display_name: str
    user_id: str | None
    email: str | None
    tenant_id: str
    role: str
    source: str
    resolved: bool


class MeetingParticipantResolver:
    async def resolve(self, db: AsyncSession, *, meeting: Meeting) -> list[ResolvedParticipant]:
        from meeting_intel.db.models import Tenant
        from meeting_intel.graph.client import get_graph_client
        rows = (await db.execute(select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting.id))).scalars().all()
        unresolved = [ResolvedParticipant(r.display_name, None, r.email, meeting.tenant_id,
                       r.role.value, "transcript_speaker", False) for r in rows]
        if meeting.is_historical or not settings.graph_configured:
            return unresolved
        tenant = await db.get(Tenant, meeting.tenant_id)
        organizer = await db.get(User, meeting.organizer_id) if meeting.organizer_id else None
        if not tenant or tenant.ms_tenant_id != settings.ms_tenant_id or not organizer or organizer.tenant_id != meeting.tenant_id or not organizer.ms_object_id:
            return unresolved
        graph = get_graph_client()
        online = await graph.find_online_meeting(organizer_user_id=organizer.ms_object_id, join_meeting_id=meeting.ms_meeting_id)
        records = await graph.get_attendance_report(organizer_user_id=organizer.ms_object_id, online_meeting_id=online["id"], strict=True)
        result = []
        seen = set()
        for record in records:
            identity = record.get("identity") or {}
            uid = identity.get("id")
            # Only attendance records explicitly tied to this Entra tenant are identities.
            # Anonymous, external, ACS and missing-tenant records remain unresolved.
            valid = bool(uid and identity.get("tenantId") == tenant.ms_tenant_id and identity.get("userIdentityType") == "aadUser")
            if valid:
                from uuid import UUID
                try:
                    uid = str(UUID(uid))
                except ValueError:
                    valid = False
            key = uid if valid else (identity.get("displayName"), record.get("emailAddress"))
            if key in seen:
                continue
            seen.add(key)
            result.append(ResolvedParticipant(identity.get("displayName") or "Unknown", uid if valid else None,
                record.get("emailAddress"), meeting.tenant_id, record.get("role", "Attendee"), "teams_attendance", valid))
        return result
