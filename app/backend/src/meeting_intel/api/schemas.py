"""Pydantic request/response schemas. Internal ORM models are never returned
directly from an endpoint — these schemas are the only API contract."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# --- Auth ---


class DevLoginRequest(BaseModel):
    email: str
    display_name: str
    tenant_name: str = Field(description="Logical tenant/workspace name for local dev auth")


class EntraCallbackRequest(BaseModel):
    code: str
    state: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    display_name: str
    tenant_id: str
    role: str


class LoginUrlResponse(BaseModel):
    login_url: str


# --- Meetings ---


class MeetingLoadRequest(BaseModel):
    meeting_id: str = Field(description="The Teams Meeting ID (numeric join id) or an internal id for manual upload")
    organizer_email: str | None = None
    title: str | None = None
    transcript_vtt: str | None = Field(
        default=None,
        description="Manual-upload fallback: raw WebVTT transcript text when Graph transcript retrieval "
        "is unavailable (see docs/RAG_ARCHITECTURE.md).",
    )


class ParticipantSchema(BaseModel):
    display_name: str
    role: str

    model_config = {"from_attributes": True}


class MeetingSummary(BaseModel):
    id: str
    ms_meeting_id: str
    title: str
    scheduled_start: datetime | None
    duration_seconds: int | None
    participant_count: int
    transcript_available: bool
    recording_available: bool
    status: str

    model_config = {"from_attributes": True}


class MeetingDetail(MeetingSummary):
    participants: list[ParticipantSchema]


# --- Chat / sources ---


class SourceSchema(BaseModel):
    speaker: str | None
    start_timestamp: str
    end_timestamp: str
    excerpt: str
    source: str = "Meeting transcript"


class ChatRequest(BaseModel):
    meeting_id: str
    conversation_id: str | None = None
    message: str


class ChatResponse(BaseModel):
    conversation_id: str
    message_id: str
    answer: str
    evidence_sufficient: bool
    cross_meeting: bool
    speaker_filter: str | None
    sources: list[SourceSchema]


class ConversationSummary(BaseModel):
    id: str
    meeting_id: str | None
    title: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageSchema(BaseModel):
    id: str
    role: str
    content: str
    sender_user_id: str | None
    created_at: datetime
    sources: list[SourceSchema] = []

    model_config = {"from_attributes": True}


class ConversationDetail(ConversationSummary):
    messages: list[MessageSchema]


# --- Groups ---


class GroupCreateRequest(BaseModel):
    name: str
    member_user_ids: list[str] = Field(default_factory=list)


class GroupSummary(BaseModel):
    id: str
    name: str
    member_count: int

    model_config = {"from_attributes": True}


class GroupMessageRequest(BaseModel):
    content: str
    ask_ai: bool = Field(default=False, description="If true, the AI Discussion Agent also responds")


class GroupMessageSchema(BaseModel):
    id: str
    sender_user_id: str | None
    sender_name: str
    content: str
    created_at: datetime


# --- Share to group / discussions ---


class ShareToGroupRequest(BaseModel):
    group_id: str
    topic: str | None = None


class DiscussionSummary(BaseModel):
    id: str
    group_id: str
    meeting_id: str | None
    topic: str

    model_config = {"from_attributes": True}


class DecisionConfirmRequest(BaseModel):
    decision_text: str
    action_items: list[dict] = Field(default_factory=list, description='[{"task": ..., "owner_name": ...}]')


class DecisionSchema(BaseModel):
    id: str
    decision_text: str
    status: str

    model_config = {"from_attributes": True}


class ActionItemSchema(BaseModel):
    id: str
    task: str
    owner_name: str | None
    status: str

    model_config = {"from_attributes": True}


# --- Feedback ---


class FeedbackRequest(BaseModel):
    rating: str = Field(pattern="^(up|down)$")
    reason: str | None = None
    comment: str | None = None
