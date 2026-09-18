# API Reference

Base URL: `http://localhost:8000` (local dev). All endpoints except `/health` and `/api/auth/*`
require `Authorization: Bearer <token>`, obtained from the auth endpoints below. Full interactive
docs are also available at `/docs` (Swagger UI) once the backend is running.

Request/response bodies are typed via Pydantic schemas in `app/backend/src/meeting_intel/api/schemas.py`
— internal ORM models are never returned directly.

## Auth

| Endpoint | Method | Description |
|---|---|---|
| `/api/auth/provider` | GET | Returns the active auth provider (`dev` or `entra`). |
| `/api/auth/dev-login` | POST | Development-only login. `{email, display_name, tenant_name}` → session token. Disabled when `AUTH_PROVIDER != dev` or `APP_ENV=production`. |
| `/api/auth/entra/login-url` | GET | Returns the Microsoft Entra ID OIDC authorization URL. Requires `AUTH_PROVIDER=entra` and real Azure AD credentials — returns `503` otherwise. |
| `/api/auth/entra/callback` | POST | Exchanges an authorization `code` for tokens, upserts the tenant/user, returns a session token. |

## Meetings

| Endpoint | Method | Description |
|---|---|---|
| `/api/meetings/load` | POST | `{meeting_id, title?, transcript_vtt?}`. Without `transcript_vtt`, attempts real Microsoft Graph lookup (`503` if Graph isn't configured). With `transcript_vtt`, uses the manual-upload ingestion path. Indexes the transcript synchronously and returns the meeting. |
| `/api/meetings` | GET | Meetings the caller is authorized to see (organizer, participant, or tenant admin), live and historical alike. Each includes `is_historical` and `document_count`. |
| `/api/meetings/{meeting_id}` | GET | Meeting detail + participants + `documents` (supporting files imported via Historical Meeting Data Import, if any). `404` if not found or not authorized (identical response either way — existence is never revealed to an unauthorized caller). |
| `/api/meetings/{meeting_id}/search` | GET | `?q=...` — direct hybrid search over one meeting's transcript **and** any imported documents, no LLM call. Powers the Search tab. Each result includes citation metadata (`source_file`, `file_type`, `document_type`, `page_number`, `sheet_name`, `slide_number`, `section`). |
| `/api/meetings/{meeting_id}/sources` | GET | All indexed chunks for a meeting — transcript and documents alike (raw source browser). |
| `/api/meetings/{meeting_id}/intelligence` | GET | `?q=...` — Related Intelligence sidebar (topics, documents, people, ideas, optional web research) for a query, without an LLM call. Powers the Search page's sidebar; see `docs/SEARCH_INTELLIGENCE.md`. |
| `/api/meetings/{meeting_id}/participants/resolved` | GET | Resolves this meeting's participants to Entra identities where possible (`MeetingParticipantResolver`) — each entry reports `resolved: true/false` and never guesses an id from a display name alone. |

## Historical Meeting Data Import

See `docs/HISTORICAL_IMPORT.md` for the full pipeline, meeting-association rules, and security model.

| Endpoint | Method | Description |
|---|---|---|
| `/api/historical-imports` | POST | Multipart file upload (a whole folder — each file's multipart filename carries its `webkitRelativePath`). Returns `{id, status: "queued", ...}` immediately; processing runs in the background. |
| `/api/historical-imports/{job_id}` | GET | Poll job progress: `total_files`, `processed_files`, `successful_files`, `skipped_files`, `failed_files`, `current_file`, `status`. |
| `/api/historical-imports/{job_id}/results` | GET | Per-file outcome (`success`/`skipped`/`failed`/`duplicate`, `reason`, `recommended_action`) once processed. |
| `/api/historical-imports` | GET | Import history for the caller's tenant, newest first. |

## Chat / conversations

| Endpoint | Method | Description |
|---|---|---|
| `/api/chat` | POST | `{meeting_id, conversation_id?, message}` → grounded answer + sources + `intelligence` (Related Intelligence sidebar, see `docs/SEARCH_INTELLIGENCE.md`). Creates a conversation if `conversation_id` is omitted. |
| `/api/conversations` | GET | The caller's private conversations. |
| `/api/conversations/{conversation_id}` | GET | Full message history + sources for one conversation. `404` if it belongs to another user. |

## Groups

| Endpoint | Method | Description |
|---|---|---|
| `/api/groups` | POST | `{name, member_user_ids?}` — create a group; creator is auto-added. |
| `/api/groups` | GET | Groups the caller is a member of. |
| `/api/groups/{group_id}/members` | GET | Returns `{members: [{id, display_name, email}], can_manage}` to group members and administrators in the same organization. |
| `/api/groups/{group_id}/members` | POST | `{email}` adds an existing user in the same organization. Only the creator or an administrator can add members. Repeated additions are harmless. New members can read existing group messages; this does not send invitations or change Teams membership. |
| `/api/groups/{group_id}/messages` | GET | Group message history. |
| `/api/groups/{group_id}/messages` | POST | `{content, ask_ai?}` — post a message; if `ask_ai`, the Discussion Agent also replies. Broadcasts over WebSocket. |
| `/api/groups/{group_id}/ws` | WebSocket | `?token=<session token>` — real-time message delivery. |

## Sharing / feedback

| Endpoint | Method | Description |
|---|---|---|
| `/api/messages/{message_id}/share` | POST | `{group_id, topic?}` — "Discuss with Group": posts a condensed context card (not the full transcript) into the group, creates a `Discussion`. |
| `/api/messages/{message_id}/feedback` | POST | `{rating: "up"\|"down", reason?, comment?}` — feedback on an AI message. |
| `/api/feedback` | GET | Feedback rows for evaluation (own submissions, or all tenant feedback for admins). |

## Discussions / decisions / action items

| Endpoint | Method | Description |
|---|---|---|
| `/api/discussions` | POST | `{group_id, meeting_id?, topic}` — create a discussion thread directly. |
| `/api/discussions/{discussion_id}/suggested-decision` | GET | Runs the Decision Agent over the group's history; returns a suggestion **without persisting it**. |
| `/api/discussions/{discussion_id}/decisions` | POST | `{decision_text, action_items}` — human-confirmed decision capture; creates `Decision` (status `confirmed`) + `ActionItem` rows. |
| `/api/discussions/groups/{group_id}/decisions` | GET | Confirmed decisions for a group. |
| `/api/discussions/groups/{group_id}/action-items` | GET | Action items for a group. |
| `/api/discussions/find-teams-group` | POST | `{meeting_id}` — resolves meeting participants to Entra identities and searches the caller's own Teams chats (delegated Graph token) for an existing group matching them. Returns `teams_available: false` with a reason if Graph isn't configured or the caller has no stored Teams consent — never a fabricated match. See `docs/SEARCH_INTELLIGENCE.md` ("Discuss with Group v2"). |
| `/api/discussions/create-teams-group` | POST | `{meeting_id, participant_user_ids, topic, confirmed: true}` — creates a real Teams group chat via Microsoft Graph. Every participant id is re-validated server-side against the meeting's resolved/authorized participants before any Graph call; `400` if any id isn't authorized. Binds the new chat to an application `Group` + `TeamsMapping`. |
| `/api/discussions/send-teams-discussion` | POST | `{meeting_id, group_id, message_id, recipient_user_ids, topic, summary, question, confirmed: true}` — sends a concise, evidence-grounded message (never raw retrieval context) into a Teams-mapped group chat. Re-fetches the chat's live membership from Graph immediately before sending and rejects (`403`) if the caller is no longer a member. |

## Health

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | `{status, graph_configured, llm_configured, auth_provider}` — used by the Settings page and deployment health checks. |

## Error shape

Unhandled errors return `{"detail": "Internal server error", "request_id": "..."}` — never a
stack trace (see `main.py`'s global exception handler). Expected errors (`401`/`403`/`404`/`503`)
return `{"detail": "<message>"}`.

Teams sends load the saved answer and source excerpts from the authorized private conversation. Client summary/evidence fields are retained for compatibility but are not trusted or sent. Recipient IDs must exactly match current Graph membership and be resolved meeting attendees or the caller. Membership changes return 409. Chat responses additionally contain bounded `evidence` and `intelligence`.
