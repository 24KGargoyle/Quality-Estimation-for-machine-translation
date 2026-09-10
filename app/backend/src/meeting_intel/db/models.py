"""SQLAlchemy models for the Meeting Intelligence platform.

Tenant isolation: every row that can be queried by an end user carries (directly
or via its parent) a `tenant_id`. All repository/query helpers in
`meeting_intel.security.authz` filter by the caller's tenant_id in addition to
row-level authorization — a user can never see rows from another tenant even
if they guess an id.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from meeting_intel.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class UUIDPk:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------------------
# Tenancy / Users
# --------------------------------------------------------------------------


class Tenant(Base, UUIDPk, TimestampMixin):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ms_tenant_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)


class UserRole(str, enum.Enum):
    member = "member"
    admin = "admin"


class User(Base, UUIDPk, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    ms_object_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.member)


# --------------------------------------------------------------------------
# Meetings
# --------------------------------------------------------------------------


class MeetingStatus(str, enum.Enum):
    pending = "pending"
    indexing = "indexing"
    ready = "ready"
    failed = "failed"
    no_transcript = "no_transcript"


class Meeting(Base, UUIDPk, TimestampMixin):
    __tablename__ = "meetings"
    __table_args__ = (UniqueConstraint("tenant_id", "ms_meeting_id", name="uq_meetings_tenant_msid"),)

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    ms_meeting_id: Mapped[str] = mapped_column(String(512), index=True)
    title: Mapped[str] = mapped_column(String(500))
    organizer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcript_available: Mapped[bool] = mapped_column(Boolean, default=False)
    recording_available: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[MeetingStatus] = mapped_column(Enum(MeetingStatus), default=MeetingStatus.pending, index=True)

    participants: Mapped[list["MeetingParticipant"]] = relationship(back_populates="meeting", cascade="all, delete-orphan")


class ParticipantRole(str, enum.Enum):
    organizer = "organizer"
    attendee = "attendee"


class MeetingParticipant(Base, UUIDPk):
    __tablename__ = "meeting_participants"
    __table_args__ = (Index("ix_meeting_participants_meeting_user", "meeting_id", "user_id"),)

    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    role: Mapped[ParticipantRole] = mapped_column(Enum(ParticipantRole), default=ParticipantRole.attendee)

    meeting: Mapped[Meeting] = relationship(back_populates="participants")


class TranscriptSource(str, enum.Enum):
    graph = "graph"
    manual_upload = "manual_upload"


class MeetingTranscript(Base, UUIDPk, TimestampMixin):
    __tablename__ = "meeting_transcripts"
    __table_args__ = (UniqueConstraint("meeting_id", name="uq_meeting_transcripts_meeting"),)

    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    source: Mapped[TranscriptSource] = mapped_column(Enum(TranscriptSource), default=TranscriptSource.graph)
    raw_format: Mapped[str] = mapped_column(String(32), default="vtt")
    storage_ref: Mapped[str] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TranscriptChunk(Base, UUIDPk, TimestampMixin):
    __tablename__ = "transcript_chunks"
    __table_args__ = (
        Index("ix_transcript_chunks_meeting", "meeting_id"),
        Index("ix_transcript_chunks_speaker", "speaker"),
        Index("ix_transcript_chunks_meeting_speaker", "meeting_id", "speaker"),
    )

    meeting_id: Mapped[str] = mapped_column(ForeignKey("meetings.id", ondelete="CASCADE"), index=True)
    transcript_id: Mapped[str] = mapped_column(ForeignKey("meeting_transcripts.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    # Stored as plain JSON (a list of floats) rather than a pgvector column so this app
    # needs nothing beyond stock PostgreSQL — no extension to install/compile. Cosine
    # similarity is computed in Python at query time (retrieval/hybrid_search.py); see
    # docs/RAG_ARCHITECTURE.md for the tradeoff this makes against a DB-side ANN index.
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)


# --------------------------------------------------------------------------
# Conversations (private AI chat) & Groups
# --------------------------------------------------------------------------


class ConversationKind(str, enum.Enum):
    private_meeting = "private_meeting"
    private_general = "private_general"


class Conversation(Base, UUIDPk, TimestampMixin):
    __tablename__ = "conversations"

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    meeting_id: Mapped[str | None] = mapped_column(ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True, index=True)
    kind: Mapped[ConversationKind] = mapped_column(Enum(ConversationKind), default=ConversationKind.private_meeting)
    title: Mapped[str] = mapped_column(String(255), default="New conversation")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ConversationMember(Base, UUIDPk):
    __tablename__ = "conversation_members"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id", name="uq_conv_member"),)

    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))


class Group(Base, UUIDPk, TimestampMixin):
    __tablename__ = "groups"

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class GroupMember(Base, UUIDPk):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_member"),)

    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False)


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class Message(Base, UUIDPk, TimestampMixin):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "(conversation_id IS NOT NULL AND group_id IS NULL) OR "
            "(conversation_id IS NULL AND group_id IS NOT NULL)",
            name="ck_message_single_parent",
        ),
        Index("ix_messages_conversation", "conversation_id"),
        Index("ix_messages_group", "group_id"),
    )

    conversation_id: Mapped[str | None] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True)
    group_id: Mapped[str | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)
    sender_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole))
    content: Mapped[str] = mapped_column(Text)
    shared_from_message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    meeting_id: Mapped[str | None] = mapped_column(ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True)


class AIResponse(Base, UUIDPk, TimestampMixin):
    __tablename__ = "ai_responses"
    __table_args__ = (UniqueConstraint("message_id", name="uq_ai_response_message"),)

    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    meeting_id: Mapped[str | None] = mapped_column(ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True)
    retrieval_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_sufficient: Mapped[bool] = mapped_column(Boolean, default=True)
    model: Mapped[str] = mapped_column(String(128))
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AISource(Base, UUIDPk):
    __tablename__ = "ai_sources"

    ai_response_id: Mapped[str] = mapped_column(ForeignKey("ai_responses.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("transcript_chunks.id", ondelete="CASCADE"))
    speaker: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_seconds: Mapped[float] = mapped_column(Float)
    end_seconds: Mapped[float] = mapped_column(Float)
    excerpt: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float)


# --------------------------------------------------------------------------
# Feedback
# --------------------------------------------------------------------------


class FeedbackRating(str, enum.Enum):
    up = "up"
    down = "down"


class FeedbackReason(str, enum.Enum):
    incorrect_answer = "incorrect_answer"
    wrong_speaker = "wrong_speaker"
    wrong_meeting = "wrong_meeting"
    missing_information = "missing_information"
    wrong_timestamp = "wrong_timestamp"
    not_relevant = "not_relevant"
    other = "other"


class Feedback(Base, UUIDPk, TimestampMixin):
    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_feedback_message_user"),)

    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    meeting_id: Mapped[str | None] = mapped_column(ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True)
    rating: Mapped[FeedbackRating] = mapped_column(Enum(FeedbackRating))
    reason: Mapped[FeedbackReason | None] = mapped_column(Enum(FeedbackReason), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_source_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)


# --------------------------------------------------------------------------
# Discussions / Decisions / Action items
# --------------------------------------------------------------------------


class Discussion(Base, UUIDPk, TimestampMixin):
    """A 'Discuss with Group' thread: an AI answer shared into a group."""

    __tablename__ = "discussions"

    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    meeting_id: Mapped[str | None] = mapped_column(ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True)
    shared_message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    topic: Mapped[str] = mapped_column(String(500))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class DecisionStatus(str, enum.Enum):
    potential = "potential"
    confirmed = "confirmed"
    rejected = "rejected"


class Decision(Base, UUIDPk, TimestampMixin):
    __tablename__ = "decisions"

    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    discussion_id: Mapped[str | None] = mapped_column(ForeignKey("discussions.id", ondelete="SET NULL"), nullable=True)
    meeting_id: Mapped[str | None] = mapped_column(ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True)
    decision_text: Mapped[str] = mapped_column(Text)
    status: Mapped[DecisionStatus] = mapped_column(Enum(DecisionStatus), default=DecisionStatus.potential)
    source_message_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActionItemStatus(str, enum.Enum):
    open = "open"
    in_progress = "in_progress"
    done = "done"


class ActionItemSource(str, enum.Enum):
    group_discussion = "group_discussion"
    meeting = "meeting"


class ActionItem(Base, UUIDPk, TimestampMixin):
    __tablename__ = "action_items"

    group_id: Mapped[str | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, index=True)
    meeting_id: Mapped[str | None] = mapped_column(ForeignKey("meetings.id", ondelete="SET NULL"), nullable=True)
    decision_id: Mapped[str | None] = mapped_column(ForeignKey("decisions.id", ondelete="SET NULL"), nullable=True)
    task: Mapped[str] = mapped_column(Text)
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[ActionItemStatus] = mapped_column(Enum(ActionItemStatus), default=ActionItemStatus.open)
    source: Mapped[ActionItemSource] = mapped_column(Enum(ActionItemSource), default=ActionItemSource.group_discussion)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# --------------------------------------------------------------------------
# Teams integration mapping
# --------------------------------------------------------------------------


class TeamsMapping(Base, UUIDPk, TimestampMixin):
    __tablename__ = "teams_mappings"

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[str | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, unique=True)
    teams_chat_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    teams_channel_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    teams_team_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


# --------------------------------------------------------------------------
# Audit log
# --------------------------------------------------------------------------


class AuditLog(Base, UUIDPk, TimestampMixin):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_tenant_created", "tenant_id", "created_at"),)

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(128))
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
