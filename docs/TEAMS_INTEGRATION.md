# Teams Integration

Microsoft Teams integration is untouched by the PostgreSQL-removal refactor — this document
describes it as it exists today. See `docs/MICROSOFT_GRAPH_PERMISSIONS.md` for the exact Graph
app registration and permissions.

## Meeting resolution and transcript retrieval

```
POST /api/meetings/load {ms_meeting_id, tenant}
   │
   ▼
security/authz — resolves and authorizes the caller against this tenant before any Graph call
   │
   ▼
graph/client.GraphClient.find_online_meeting(join_id)   — resolves a Teams "Join Meeting ID"
                                                           to Graph's internal onlineMeeting id
   │
   ▼
graph/client.GraphClient.get_transcripts(meeting_id)     — lists available transcripts
   │
   ▼
graph/client.GraphClient.get_transcript_content_vtt(...) — downloads the WebVTT transcript
   │
   ▼
graph/client.GraphClient.get_attendance_report(...)      — best-effort participant list
   │
   ▼
ingestion/pipeline.py — parses, chunks, embeds, indexes (see docs/RAG_ARCHITECTURE.md)
```

If Graph is not configured (`graph_configured=false` — no `MS_TENANT_ID`/`MS_CLIENT_ID`/
`MS_CLIENT_SECRET`), the endpoint returns `503` rather than fabricating meeting data — covered by
`tests/integration/test_meeting_ingestion.py::test_graph_not_configured_returns_503_without_fabricating_data`.
A manual-upload path (`POST /api/meetings/load` with `transcript_vtt` supplied directly) exists
for meetings whose transcript isn't reachable via Graph, or for development without a live tenant.
A third path, **Historical Meeting Data Import** (`POST /api/historical-imports`, see
`docs/HISTORICAL_IMPORT.md`), ingests a whole folder of past transcripts and supporting documents
in one batch — all three paths converge on the same indexing pipeline
(`retrieval/search_provider.SearchProvider`), so a historical meeting behaves identically to a
live one everywhere else in the app (chat, search, decisions, action items, feedback, sharing).

## Authorization — never trusting client-supplied identifiers

Every Graph-backed lookup is authorized **before** the Graph call, never after: the caller's
tenant and meeting-participant/organizer status are verified server-side
(`security/authz.get_authorized_meeting`) from the authenticated session, not from any
`meeting_id`/`organizer_email`/`ms_meeting_id`/`chat_id`/`team_id`/`channel_id`/`tenant_id` value
the frontend supplies in a request body. A cross-tenant or non-participant request receives `404`
or `403` — never a Graph-sourced payload for a meeting the caller isn't authorized to see. This is
covered by `tests/integration/test_authz.py` (cross-tenant, non-participant cases).

The (dead) `organizer_email` field that once existed on `MeetingLoadRequest` — read nowhere,
verified by a repo-wide grep before removal — was deleted during this refactor's security pass,
since an unused, client-supplied identifier field on an authorization-sensitive request is a
standing risk even when currently unread.

## Teams collaboration: chat, groups, "Discuss with Group"

Kept behind the `ConversationProvider` abstraction (`conversations/provider.py`) — the AI agents
(`agents/answer_agent.py`, `agents/discussion_agent.py`, `agents/decision_agent.py`) never call
the Graph API directly; they only ever produce a message, which a `ConversationProvider`
implementation then delivers:

- **`InternalChatProvider`**: for groups that are purely internal to this app (not Teams-mapped).
- **`TeamsChatProvider`**: for groups mapped to a real Teams chat or channel
  (`teams_mappings` table) — posts via `graph/client.GraphClient.send_chat_message` using the
  `Chat.ReadWrite`/`ChannelMessage.Send` application permissions.

"Discuss with Group" only ever posts a condensed, explicitly user-triggered context card into the
mapped Teams chat/channel — never the full transcript, and never automatically in the background.

## Entra ID security

- OAuth `state` is generated and persisted server-side (`security/session_security.create_oauth_state`,
  the `oauth_states` table) before the login URL is even issued, and is validated + consumed
  (single-use) on callback, **before** any MSAL/Graph call — a client-supplied or previously-used
  state is rejected with `401`. See `docs/MIGRATION_FROM_POSTGRES.md` ("Security fixes") and
  `tests/integration/test_auth_security.py`.
- Session tokens are JWTs with an `exp` claim (checked on every request) and a `jti` claim, which
  `POST /api/auth/logout` records in the `revoked_tokens` table — every subsequent request with
  that token is rejected with `401 "Session has been logged out"`, verified not to affect other
  users' tokens.
- Unauthorized resource access (wrong tenant, non-participant meeting, non-member group, a
  Teams-mapped group the caller isn't a member of) returns `401`/`403`/`404` as appropriate —
  never a silently-scoped-down response.

## What was NOT changed by the PostgreSQL removal

Every piece of this integration — Graph client, `ConversationProvider`, Entra auth, authorization
checks — was already storage-agnostic (it read/wrote through the ORM for relational state, never
raw PostgreSQL SQL), so none of it required changes for the database/search migration. The only
Teams/Graph-adjacent changes made were the three security fixes listed in
`docs/MIGRATION_FROM_POSTGRES.md`, found during the same audit pass.

## Verified in this environment

Graph/Teams/Entra code paths are real, working MSAL/Graph client and `httpx`-based calls, but are
**inert** (return `503`/require `AUTH_PROVIDER=entra`) since no Azure AD app registration is
available in this development environment — see `docs/MICROSOFT_GRAPH_PERMISSIONS.md`. No live
Teams meeting, transcript, or chat message has been exercised end-to-end against a real tenant
here; the OAuth-state and logout fixes are tested against this app's own authorization logic
(which runs before any real Graph/MSAL call), not against a live Entra ID tenant.
