# Microsoft Graph Permissions

This platform's Graph integration (`app/backend/src/meeting_intel/graph/client.py`,
`auth/entra.py`) requires an **Azure AD app registration** that does not exist in this
development environment. Everything below is real, working MSAL/Graph client code — it is
simply inert (returns `503 graph_not_configured`) until these are provisioned. See
`ARCHITECTURE_ASSESSMENT.md` and `docs/DEPLOYMENT.md` for how to supply them.

## App registration

- **Redirect URI**: `{MS_REDIRECT_URI}` (web platform, authorization code + PKCE flow), used for
  user sign-in (`auth/entra.py`).
- **Client credentials flow**: used for server-side meeting/transcript retrieval
  (`graph/client.py`), since a backend job needs to read a meeting's transcript independent of
  any interactively signed-in user's token lifetime.

## Permissions requested (least privilege)

| Permission | Type | Why it's needed | Where used | Admin consent |
|---|---|---|---|---|
| `User.Read` | Delegated | Read the signed-in user's own profile (name, email, object id) to create/match their account. | `auth/entra.py` sign-in | No |
| `OnlineMeetings.Read.All` | Application | Look up a Teams meeting by its numeric Meeting ID (`JoinMeetingId`) and read its metadata (subject, organizer). | `graph/client.py: find_online_meeting` | Yes |
| `OnlineMeetingTranscript.Read.All` | Application | Read the meeting's transcript content (WebVTT) — the core input to the whole platform. | `graph/client.py: get_transcripts`, `get_transcript_content_vtt` | Yes |
| `OnlineMeetingArtifact.Read.All` | Application | Read attendance reports for participant lists (best-effort; falls back gracefully if unavailable). | `graph/client.py: get_attendance_report` | Yes |
| `Chat.ReadWrite` | Application | Post the AI-shared meeting context card into a Teams chat when "Discuss with Group" targets a Teams-mapped group. | `graph/client.py: send_chat_message`, `conversations/provider.py: TeamsChatProvider` | Yes |
| `ChannelMessage.Send` | Application | Same as above, for a Teams channel rather than a 1:1/group chat. | (extension point in `TeamsChatProvider`; channel posting follows the same `send_chat_message`-style call against the channel messages endpoint) | Yes |

**Not requested**: `Mail.*`, `Files.*`, `Directory.*`, `User.ReadWrite.All`, or any permission
broader than what the meeting-intelligence and group-sharing features actually need. Application
permissions additionally require a **Cloud Communications application access policy**
(`Grant-CsApplicationAccessPolicy`) scoping which organizers' meetings this app may read —
without it, `OnlineMeetings.Read.All`/`OnlineMeetingTranscript.Read.All` alone are not sufficient
to read a given organizer's meetings, even with admin consent. This is Microsoft's own
least-privilege mechanism on top of app registration and is documented here so whoever
provisions the tenant applies it per-organizer rather than tenant-wide.

## Security implications

- Application-permission tokens (client credentials) grant this backend service the ability to
  read *any* meeting covered by the application access policy — treat `MS_CLIENT_SECRET` as a
  high-value secret (see `docs/SECURITY.md`: never committed, rotated via the deployment's
  secret manager).
- Because transcript content can include anything said in the meeting, it is treated as
  untrusted data everywhere it's used in a prompt (`docs/AGENT_ARCHITECTURE.md`,
  prompt-injection section of `docs/SECURITY.md`) — Graph read access does not imply the
  transcript content is trusted instruction text.
- `Chat.ReadWrite`/`ChannelMessage.Send` let this app post messages as itself into Teams
  conversations; the "Discuss with Group" flow only ever posts a condensed, explicitly-user-
  triggered context card — never the full transcript, and never automatically.
