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
| `/api/meetings/load` | POST | `{meeting_id, organizer_email?, title?, transcript_vtt?}`. Without `transcript_vtt`, attempts real Microsoft Graph lookup (`503` if Graph isn't configured). With `transcript_vtt`, uses the manual-upload ingestion path. Indexes the transcript synchronously and returns the meeting. |
| `/api/meetings` | GET | Meetings the caller is authorized to see (organizer, participant, or tenant admin). |
| `/api/meetings/{meeting_id}` | GET | Meeting detail + participants. `404` if not found or not authorized (identical response either way — existence is never revealed to an unauthorized caller). |
| `/api/meetings/{meeting_id}/search` | GET | `?q=...` — direct hybrid search over one meeting's transcript, no LLM call. Powers the Search tab. |
| `/api/meetings/{meeting_id}/sources` | GET | All transcript chunks for a meeting (raw source browser). |

## Chat / conversations

| Endpoint | Method | Description |
|---|---|---|
| `/api/chat` | POST | `{meeting_id, conversation_id?, message}` → grounded answer + sources. Creates a conversation if `conversation_id` is omitted. |
| `/api/conversations` | GET | The caller's private conversations. |
| `/api/conversations/{conversation_id}` | GET | Full message history + sources for one conversation. `404` if it belongs to another user. |

## Groups

| Endpoint | Method | Description |
|---|---|---|
| `/api/groups` | POST | `{name, member_user_ids?}` — create a group; creator is auto-added. |
| `/api/groups` | GET | Groups the caller is a member of. |
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

## Health

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | `{status, graph_configured, llm_configured, auth_provider}` — used by the Settings page and deployment health checks. |

## Error shape

Unhandled errors return `{"detail": "Internal server error", "request_id": "..."}` — never a
stack trace (see `main.py`'s global exception handler). Expected errors (`401`/`403`/`404`/`503`)
return `{"detail": "<message>"}`.
