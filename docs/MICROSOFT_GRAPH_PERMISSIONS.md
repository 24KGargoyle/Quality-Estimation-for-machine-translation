# Microsoft Graph permission matrix

The existing FastAPI/Next.js, Azure SQL, Azure AI Search and Azure OpenAI architecture is retained. Teams integration is optional; no PostgreSQL or pgvector is required.

| Operation | Permission | Context | Endpoint |
| --- | --- | --- | --- |
| Signed-in profile | User.Read | Delegated | GET /me |
| List accessible chats | Chat.ReadBasic | Delegated | GET /me/chats |
| Inspect complete chat membership | ChatMember.Read | Delegated | GET /chats/{id}/members |
| Create a confirmed group | Chat.Create | Delegated | POST /chats |
| Send a confirmed discussion | ChatMessage.Send | Delegated | POST /chats/{id}/messages |
| Meeting discovery | OnlineMeetings.Read.All | Application | GET /users/{organizer}/onlineMeetings |
| Transcript ingestion | OnlineMeetingTranscript.Read.All | Application | GET .../transcripts |
| Attendance resolution | OnlineMeetingArtifact.Read.All | Application | GET .../attendanceReports/.../attendanceRecords |

Application meeting permissions require admin consent and a Teams application access policy scoped to permitted organizers. Delegated consent remains subject to tenant policy. No directory-wide user lookup, app-only chat sending, Mail or Files permissions are needed by this workflow.

## Configuration and trust

Set MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET, MS_REDIRECT_URI and AUTH_PROVIDER=entra. Set GRAPH_TOKEN_ENCRYPTION_KEY to a dedicated Fernet key stored as a deployment secret, then sign in again. Tokens are encrypted at rest, never returned to the browser, and refreshed server-side. Losing or rotating the key requires reauthentication. Run `alembic upgrade head` to add the token table.

Only actual attendance identities explicitly associated with the configured Entra tenant are resolved. Historical names, external attendees and incomplete records remain unresolved; no name or email guessing is used. Chat lists and member lists are paginated. Matching requires exact identity sets; extra or unknown members prevent a match. User, meeting, group, message and mapping authorization is checked server-side. Caller membership is checked again before sending. Local group sharing stays internal, even for a mapped group.

Creation requires `confirmed: true`; sending is a separate confirmation and requires a saved `message_id`. Saved answer and references are loaded server-side and escaped before Teams HTML rendering. Graph failures return unavailable/error states and never simulated success. After a timeout, check Teams before retrying because Graph may have accepted a request before the response was lost.

## Microsoft documentation

- [List chats](https://learn.microsoft.com/en-us/graph/api/chat-list?view=graph-rest-1.0)
- [List chat members](https://learn.microsoft.com/en-us/graph/api/chat-list-members?view=graph-rest-1.0)
- [Create chat](https://learn.microsoft.com/en-us/graph/api/chat-post?view=graph-rest-1.0)
- [Send chat message](https://learn.microsoft.com/en-us/graph/api/chat-post-messages?view=graph-rest-1.0)
- [Attendance record](https://learn.microsoft.com/en-us/graph/api/resources/attendancerecord?view=graph-rest-1.0)

Live tenant consent, application access policy and Teams delivery still require deployment validation. Mocked tests do not establish those capabilities.
