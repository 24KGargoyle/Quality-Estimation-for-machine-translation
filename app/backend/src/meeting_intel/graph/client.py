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

    async def get_attendance_report(self, *, organizer_user_id: str, online_meeting_id: str) -> list[dict]:
        """Best-effort participant list via the latest attendance report. Returns [] on failure."""
        self._require_configured()
        try:
            reports = await self._get(
                f"{GRAPH_BASE}/users/{organizer_user_id}/onlineMeetings/{online_meeting_id}/attendanceReports"
            )
            values = reports.get("value", [])
            if not values:
                return []
            latest = values[-1]["id"]
            records = await self._get(
                f"{GRAPH_BASE}/users/{organizer_user_id}/onlineMeetings/{online_meeting_id}"
                f"/attendanceReports/{latest}/attendanceRecords"
            )
            return records.get("value", [])
        except (GraphMeetingNotFoundError, GraphTransientError, httpx.HTTPStatusError):
            return []

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


_client: GraphClient | None = None


def get_graph_client() -> GraphClient:
    global _client
    if _client is None:
        _client = GraphClient()
    return _client
