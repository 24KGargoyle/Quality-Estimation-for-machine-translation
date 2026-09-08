export interface TokenResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  display_name: string;
  tenant_id: string;
  role: string;
}

export interface MeetingSummary {
  id: string;
  ms_meeting_id: string;
  title: string;
  scheduled_start: string | null;
  duration_seconds: number | null;
  participant_count: number;
  transcript_available: boolean;
  recording_available: boolean;
  status: string;
}

export interface ParticipantSchema {
  display_name: string;
  role: string;
}

export interface MeetingDetail extends MeetingSummary {
  participants: ParticipantSchema[];
}

export interface SourceSchema {
  speaker: string | null;
  start_timestamp: string;
  end_timestamp: string;
  excerpt: string;
  source: string;
}

export interface ChatResponse {
  conversation_id: string;
  message_id: string;
  answer: string;
  evidence_sufficient: boolean;
  cross_meeting: boolean;
  speaker_filter: string | null;
  sources: SourceSchema[];
}

export interface MessageSchema {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  sender_user_id: string | null;
  created_at: string;
  sources: SourceSchema[];
}

export interface ConversationSummary {
  id: string;
  meeting_id: string | null;
  title: string;
  updated_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: MessageSchema[];
}

export interface GroupSummary {
  id: string;
  name: string;
  member_count: number;
}

export interface GroupMessageSchema {
  id: string;
  sender_user_id: string | null;
  sender_name: string;
  content: string;
  created_at: string;
}

export interface DiscussionSummary {
  id: string;
  group_id: string;
  meeting_id: string | null;
  topic: string;
}

export interface DecisionSchema {
  id: string;
  decision_text: string;
  status: string;
}

export interface ActionItemSchema {
  id: string;
  task: string;
  owner_name: string | null;
  status: string;
}

export interface FeedbackRow {
  id: string;
  message_id: string;
  meeting_id: string | null;
  rating: "up" | "down";
  reason: string | null;
  comment: string | null;
  question: string | null;
  answer: string | null;
  created_at: string;
}

export interface SearchResult {
  chunk_id: string;
  speaker: string | null;
  start_seconds: number;
  end_seconds: number;
  text: string;
  score: number;
}

export interface SuggestedDecision {
  detected: boolean;
  decision_text: string | null;
  action_items: { task: string; owner: string }[];
}
