"""Microsoft Entra ID (Azure AD) OIDC login via MSAL confidential client.

This is real MSAL/Graph integration code, not a mock. It is inert without a
real Azure AD app registration: `Settings.graph_configured` gates every call
here, and `get_login_url`/`acquire_token_by_auth_code` raise
`GraphNotConfiguredError` when the tenant/client credentials are absent so the
API can return a clear error instead of pretending to authenticate someone.

Required Azure AD app registration (see docs/MICROSOFT_GRAPH_PERMISSIONS.md):
  - Redirect URI: `MS_REDIRECT_URI` (web platform, authorization code flow)
  - Delegated permissions: `User.Read`, `OnlineMeetings.Read`,
    `OnlineMeetingTranscript.Read.All`, `Chat.ReadWrite`, `ChannelMessage.Send`
  - Client secret stored only in `MS_CLIENT_SECRET` (never committed)
"""
import httpx
import msal

from meeting_intel.config import get_settings

settings = get_settings()

GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/me"


class GraphNotConfiguredError(Exception):
    """Raised when Entra ID / Graph credentials are not configured."""


def _authority() -> str:
    return f"https://login.microsoftonline.com/{settings.ms_tenant_id}"


def _msal_app() -> msal.ConfidentialClientApplication:
    if not settings.graph_configured:
        raise GraphNotConfiguredError(
            "Microsoft Entra ID is not configured. Set MS_TENANT_ID, MS_CLIENT_ID, "
            "MS_CLIENT_SECRET to enable real sign-in."
        )
    return msal.ConfidentialClientApplication(
        client_id=settings.ms_client_id,
        client_credential=settings.ms_client_secret,
        authority=_authority(),
    )


def _scopes() -> list[str]:
    return [f"https://graph.microsoft.com/{s}" if "/" not in s else s for s in ["User.Read"]]


def get_login_url(state: str) -> str:
    app = _msal_app()
    return app.get_authorization_request_url(
        scopes=_scopes(),
        state=state,
        redirect_uri=settings.ms_redirect_uri,
    )


async def acquire_token_by_auth_code(code: str) -> dict:
    """Exchange an OIDC authorization code for tokens, then fetch the user profile."""
    app = _msal_app()
    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=_scopes(),
        redirect_uri=settings.ms_redirect_uri,
    )
    if "access_token" not in result:
        raise GraphNotConfiguredError(
            f"Entra ID token exchange failed: {result.get('error_description', result.get('error'))}"
        )

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            GRAPH_ME_URL,
            headers={"Authorization": f"Bearer {result['access_token']}"},
        )
        resp.raise_for_status()
        profile = resp.json()

    return {
        "access_token": result["access_token"],
        "refresh_token": result.get("refresh_token"),
        "id_token_claims": result.get("id_token_claims", {}),
        "profile": profile,
    }
