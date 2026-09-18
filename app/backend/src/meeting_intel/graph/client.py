"""Microsoft Graph client for Teams meeting discovery + transcript retrieval.

This is a real client (real MSAL app-only token acquisition, real Graph HTTP
calls) behind an interface, per the assessment in ARCHITECTURE_ASSESSMENT.md.
It requires:
  - `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET` (Azure AD app registration)
  - Application permissions with admin consent: `OnlineMeetings.Read.All`,
    `OnlineMeetingTranscript.Read.All`, `OnlineMeetingArtifact.Read.All`
  - A Cloud Communications application access policy assigned to the
    meeting organizers, granting this app permission to read their meetings

None of that exists in this development environment, so every method raises
`GraphNotConfiguredError` up front when credentials are absent — callers turn
that into a `503 graph_not_configured` HTTP response (see
`api/routers/meetings.py`) rather than returning fabricated data.

See docs/MICROSOFT_GRAPH_PERMISSIONS.md for the full permission list and
rationale.
"""
from __future__ import annotations

import httpx
import msal
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from meeting_intel.auth.entra import GraphNotConfiguredError
from meeting_intel.config import get_settings

settings = get_settings()

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphTransientError(Exception):
    """Retryable Graph failure (429/5xx)."""


class GraphMeetingNotFoundError(Exception):
    pass


class GraphClient:
    def __init__(self) -> None:
        self._app: msal.ConfidentialClientApplication | None = None

    def _require_configured(self) -> None:
        if not settings.graph_configured:
            raise GraphNotConfiguredError(
                "Microsoft Graph is not configured. Set MS_TENANT_ID, MS_CLIENT_ID, "
                "MS_CLIENT_SECRET to enable meeting discovery."
            )

    def _msal_app(self) -> msal.ConfidentialClientApplication:
        self._require_configured()
        if self._app is None:
            self._app = msal.ConfidentialClientApplication(
                client_id=settings.ms_client_id,
                client_credential=settings.ms_client_secret,
                authority=f"https://login.microsoftonline.com/{settings.ms_tenant_id}",
            )
        return self._app

    def _acquire_app_token(self) -> str:
        result = self._msal_app().acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
        if "access_token" not in result:
            raise GraphNotConfiguredError(
                f"Failed to acquire Graph app token: {result.get('error_description', result.get('error'))}"
            )
        return result["access_token"]

    @retry(
        retry=retry_if_exception_type(GraphTransientError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        reraise=True,
    )
    async def _get(self, url: str, *, params: dict | None = None) -> dict:
        token = self._acquire_app_token()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
        if resp.status_code == 404:
            raise GraphMeetingNotFoundError(url)
        if resp.status_code == 429 or resp.status_code >= 500:
            raise GraphTransientError(f"{resp.status_code}: {resp.text}")
        resp.raise_for_status()
        return resp.json()

    async def _get_text(self, url: str) -> str:
        token = self._acquire_app_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                url, headers={"Authorization": f"Bearer {token}", "Accept": "text/vtt"}
            )
        resp.raise_for_status()
        return resp.text

    async def find_online_meeting(self, *, organizer_user_id: str, join_meeting_id: str) -> dict:
        """Look up an onlineMeeting by the numeric Meeting ID shown in the Teams UI."""
        self._require_configured()
        url = f"{GRAPH_BASE}/users/{organizer_user_id}/onlineMeetings"
        data = await self._get(
            url, params={"$filter": f"JoinMeetingIdSettings/JoinMeetingId eq '{join_meeting_id}'"}
        )
        values = data.get("value", [])
        if not values:
            raise GraphMeetingNotFoundError(join_meeting_id)
        return values[0]

    async def get_transcripts(self, *, organizer_user_id: str, online_meeting_id: str) -> list[dict]:
        self._require_configured()
        url = f"{GRAPH_BASE}/users/{organizer_user_id}/onlineMeetings/{online_meeting_id}/transcripts"
        data = await self._get(url)
        return data.get("value", [])

    async def get_transcript_content_vtt(
        self, *, organizer_user_id: str, online_meeting_id: str, transcript_id: str
    ) -> str:
        self._require_configured()
        url = (
            f"{GRAPH_BASE}/users/{organizer_user_id}/onlineMeetings/{online_meeting_id}"
            f"/transcripts/{transcript_id}/content?$format=text/vtt"
        )
        return await self._get_text(url)

    async def get_attendance_report(self, *, organizer_user_id: str, online_meeting_id: str, strict: bool = False) -> list[dict]:
        """Best-effort participant list via the latest attendance report. Returns [] on failure."""
        self._require_configured()
        try:
            reports = await self._get(
                f"{GRAPH_BASE}/users/{organizer_user_id}/onlineMeetings/{online_meeting_id}/attendanceReports"
            )
            values = reports.get("value", [])
            if not values:
                return []
            latest = max(values, key=lambda r: r.get("meetingEndDateTime", ""))["id"]
            records = await self._get(
                f"{GRAPH_BASE}/users/{organizer_user_id}/onlineMeetings/{online_meeting_id}"
                f"/attendanceReports/{latest}/attendanceRecords"
            )
            result = records.get("value", [])
            visited = set()
            while records.get("@odata.nextLink"):
                url = records["@odata.nextLink"]
                self._validate_graph_url(url)
                if url in visited or len(visited) >= 100:
                    raise GraphNotConfiguredError("Attendance pagination incomplete")
                visited.add(url)
                records = await self._get(url)
                result.extend(records.get("value", []))
            return result
        except (GraphMeetingNotFoundError, GraphTransientError, httpx.HTTPStatusError):
            if strict:
                raise
            return []

    async def resolve_user_by_upn(self, upn_or_email: str) -> dict | None:
        """Best-effort app-only lookup of an Entra user by UPN/email — used
        by `teams/participant_resolver.py` to resolve a meeting attendee who
        only has an email on file (from the attendance report) into a real
        Entra object id. Returns None (never raises) when not found or on
        any transient failure, since this is explicitly best-effort: a
        failed lookup means `resolved=False` for that participant, not an
        error for the whole request."""
        self._require_configured()
        try:
            return await self._get(f"{GRAPH_BASE}/users/{upn_or_email}")
        except (GraphMeetingNotFoundError, GraphTransientError, httpx.HTTPStatusError):
            return None

    async def send_chat_message(self, *, chat_id: str, content_html: str) -> dict:
        """Post an AI-shared context message into a Teams chat (least-privilege: Chat.ReadWrite)."""
        self._require_configured()
        token = self._acquire_app_token()
        url = f"{GRAPH_BASE}/chats/{chat_id}/messages"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={"body": {"contentType": "html", "content": content_html}},
            )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Delegated user-context calls (§14 of the Search Intelligence + Teams
    # Collaboration upgrade — "prefer delegated user context"). Each takes an
    # already-acquired delegated access token (see graph/delegated_auth.py)
    # rather than the app-only token above: these act on the signed-in
    # user's own chats/permissions, never with broader app-only access.
    # ------------------------------------------------------------------

    async def _delegated_get(self, url: str, access_token: str, *, params: dict | None = None) -> dict:
        self._require_configured()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {access_token}"}, params=params)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _validate_graph_url(url: str) -> None:
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com" or not parsed.path.startswith("/v1.0/"):
            raise GraphNotConfiguredError("Invalid Graph pagination URL")

    async def _delegated_pages(self, url: str, token: str) -> list[dict]:
        result = []
        visited = set()
        while url:
            self._validate_graph_url(url)
            if url in visited or len(visited) >= 100:
                raise GraphNotConfiguredError("Graph result set could not be completely inspected.")
            visited.add(url)
            page = await self._delegated_get(url, token)
            result.extend(page.get("value", []))
            url = page.get("@odata.nextLink")
        return result

    async def list_my_group_chats(self, access_token: str) -> list[dict]:
        chats = await self._delegated_pages(f"{GRAPH_BASE}/me/chats?$top=50", access_token)
        result = []
        for chat in chats:
            if chat.get("chatType") != "group":
                continue
            chat["members"] = await self.get_chat_members(access_token, chat_id=chat["id"])
            result.append(chat)
        return result

    async def get_chat_members(self, access_token: str, *, chat_id: str) -> list[dict]:
        from urllib.parse import quote
        return await self._delegated_pages(f"{GRAPH_BASE}/chats/{quote(chat_id, safe='')}/members", access_token)

    async def create_group_chat(self, access_token: str, *, member_user_ids: list[str], topic: str) -> dict:
        """Creates a new Teams group chat containing the signed-in user plus
        each given Entra object id, with the given topic (delegated
        `Chat.ReadWrite`). Never called with unvalidated ids — the caller
        (api/routers/discussions.py) has already checked each id against the
        meeting's resolved, authorized participants."""
        self._require_configured()
        members = [
            {
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "roles": ["owner"],
                "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{uid}')",
            }
            for uid in member_user_ids
        ]
        body = {"chatType": "group", "topic": topic, "members": members}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{GRAPH_BASE}/chats", headers={"Authorization": f"Bearer {access_token}"}, json=body
            )
        resp.raise_for_status()
        return resp.json()

    async def send_chat_message_delegated(self, access_token: str, *, chat_id: str, content_html: str) -> dict:
        self._require_configured()
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{GRAPH_BASE}/chats/{chat_id}/messages",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"body": {"contentType": "html", "content": content_html}},
            )
        resp.raise_for_status()
        return resp.json()


_client: GraphClient | None = None


def get_graph_client() -> GraphClient:
    global _client
    if _client is None:
        _client = GraphClient()
    return _client
