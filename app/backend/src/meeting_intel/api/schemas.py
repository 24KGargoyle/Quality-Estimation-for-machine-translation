"""Pydantic request/response schemas. Internal ORM models are never returned
directly from an endpoint — these schemas are the only API contract."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

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
    is_historical: bool = False
    document_count: int = 0

    model_config = {"from_attributes": True}


class HistoricalDocumentSchema(BaseModel):
    id: str
    source_file: str
    relative_path: str
    file_type: str
    document_type: str
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class MeetingDetail(MeetingSummary):
    participants: list[ParticipantSchema]
    documents: list[HistoricalDocumentSchema] = []


# --- Chat / sources ---


class SourceSchema(BaseModel):
    speaker: str | None
    start_timestamp: str | None
    end_timestamp: str | None
    excerpt: str
    source: str = "Meeting transcript"
    # Historical-document citation metadata — null for a transcript source.
    source_file: str | None = None
    file_type: str = "vtt"
    document_type: str = "transcript"
    page_number: int | None = None
    sheet_name: str | None = None
    slide_number: int | None = None
    section: str | None = None


class ChatRequest(BaseModel):
    meeting_id: str
    document_id: str | None = None
    conversation_id: str | None = None
    message: str


class RelatedDocumentSchema(BaseModel):
    source_file: str
    document_type: str
    file_type: str
    location: str | None = None


class WebResultSchema(BaseModel):
    title: str
    snippet: str
    url: str


class WebResearchSchema(BaseModel):
    configured: bool
    query: str
    results: list[WebResultSchema]
    note: str | None = None


class IntelligencePanelSchema(BaseModel):
    related_topics: list[str]
    related_documents: list[RelatedDocumentSchema]
    related_people: list[str]
    ideas: list[str]
    web_research: WebResearchSchema | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    message_id: str
    answer: str
    evidence_sufficient: bool
    cross_meeting: bool
    speaker_filter: str | None
    sources: list[SourceSchema]
    evidence: list[SourceSchema] = Field(default_factory=list)
    intelligence: IntelligencePanelSchema | None = None


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


class GroupMemberSchema(BaseModel):
    id: str
    display_name: str
    email: str


class GroupMembersResponse(BaseModel):
    members: list[GroupMemberSchema]
    can_manage: bool


class GroupAddMemberRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


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


# --- Historical Meeting Data Import ---


class ImportJobSummary(BaseModel):
    id: str
    status: str
    total_files: int
    processed_files: int
    successful_files: int
    skipped_files: int
    failed_files: int
    current_file: str | None
    created_at: datetime
    created_by: str

    model_config = {"from_attributes": True}


class ImportedFileResultSchema(BaseModel):
    filename: str
    relative_path: str
    file_type: str
    status: str
    reason: str | None
    recommended_action: str | None
    document_id: str | None
    meeting_id: str | None
    chunk_count: int

    model_config = {"from_attributes": True}


class ImportJobResults(BaseModel):
    job: ImportJobSummary
    results: list[ImportedFileResultSchema]


# --- Teams Collaboration (Discuss with Group v2) ---


class ResolvedParticipantSchema(BaseModel):
    display_name: str
    user_id: str | None
    email: str | None
    role: str
    source: str
    resolved: bool


class MatchedChatSchema(BaseModel):
    chat_id: str
    topic: str | None
    member_names: list[str]
    member_ids: list[str] = Field(default_factory=list)
    match_kind: str


class FindTeamsGroupRequest(BaseModel):
    meeting_id: str


class FindTeamsGroupResponse(BaseModel):
    teams_available: bool
    unavailable_reason: str | None = None
    participants: list[ResolvedParticipantSchema]
    existing_group: MatchedChatSchema | None = None
    application_group_id: str | None = None


class CreateTeamsGroupRequest(BaseModel):
    confirmed: Literal[True]
    meeting_id: str
    participant_user_ids: list[str] = Field(min_length=1)
    topic: str


class CreateTeamsGroupResponse(BaseModel):
    application_group_id: str
    teams_chat_id: str
    topic: str
    member_names: list[str]
    member_ids: list[str] = Field(default_factory=list)


class SendTeamsDiscussionRequest(BaseModel):
    recipient_user_ids: list[str]
    confirmed: Literal[True]
    message_id: str
    meeting_id: str
    group_id: str
    topic: str
    summary: str
    question: str
    evidence_speaker: str | None = None
    evidence_timestamp: str | None = None
    evidence_excerpt: str | None = None
    evidence_source_file: str | None = None
    evidence_location: str | None = None


class SendTeamsDiscussionResponse(BaseModel):
    discussion_id: str
    message_id: str
    teams_chat_id: str
