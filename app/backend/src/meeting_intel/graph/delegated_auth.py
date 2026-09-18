"""Delegated Microsoft Graph token storage and refresh — the "prefer
delegated user context" requirement for user-initiated Teams chat actions
(listing the signed-in user's own chats, creating a group chat, sending a
message on their behalf). See docs/MICROSOFT_GRAPH_PERMISSIONS.md.

Tokens are stored server-side only (`db.models.GraphUserToken`), keyed by
user, and refreshed via MSAL's confidential-client refresh-token grant when
close to expiry. Never returned to the frontend, never logged.

Real code, inert (raises `DelegatedTokenUnavailableError`) whenever there is
nothing usable to act on — either Graph isn't configured at all, or this
particular user has never completed an Entra ID login that consented to the
Teams chat scopes (`auth.entra.CHAT_SCOPES`). Both are clearly distinguished
in the error message so the frontend can show the right call to action
rather than a generic failure.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import msal
from cryptography.fernet import Fernet, InvalidToken
from meeting_intel.db.models import Tenant
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.auth.entra import CHAT_SCOPES, GraphNotConfiguredError
from meeting_intel.config import get_settings
from meeting_intel.db.models import GraphUserToken, User

settings = get_settings()

_REFRESH_SKEW_SECONDS = 60


class DelegatedTokenUnavailableError(Exception):
    """No usable delegated Graph token for this user right now."""


def _chat_scopes_qualified() -> list[str]:
    return [f"https://graph.microsoft.com/{s}" for s in CHAT_SCOPES]


def _msal_app() -> msal.ConfidentialClientApplication:
    if not settings.graph_configured:
        raise GraphNotConfiguredError("Microsoft Graph is not configured.")
    return msal.ConfidentialClientApplication(
        client_id=settings.ms_client_id,
        client_credential=settings.ms_client_secret,
        authority=f"https://login.microsoftonline.com/{settings.ms_tenant_id}",
    )


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _cipher():
    if not settings.graph_token_encryption_key:
        raise DelegatedTokenUnavailableError("Teams token storage is not configured. Set GRAPH_TOKEN_ENCRYPTION_KEY and sign in again.")
    try:
        return Fernet(settings.graph_token_encryption_key.encode())
    except ValueError:
        raise DelegatedTokenUnavailableError("Teams token encryption key is invalid.") from None


async def store_delegated_token(
    db: AsyncSession, *, user_id: str, access_token: str, refresh_token: str | None, expires_in: int, scope: str
) -> None:
    if not settings.graph_token_encryption_key:
        return  # Sign-in remains operational; Teams stays explicitly unavailable.
    cipher = _cipher()
    access_token = cipher.encrypt(access_token.encode()).decode()
    refresh_token = cipher.encrypt(refresh_token.encode()).decode() if refresh_token else None
    existing = (
        await db.execute(select(GraphUserToken).where(GraphUserToken.user_id == user_id))
    ).scalar_one_or_none()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    if existing is not None:
        existing.access_token = access_token
        existing.refresh_token = refresh_token or existing.refresh_token
        existing.expires_at = expires_at
        existing.scope = scope
    else:
        db.add(
            GraphUserToken(
                user_id=user_id, access_token=access_token, refresh_token=refresh_token,
                expires_at=expires_at, scope=scope,
            )
        )
    await db.flush()


async def get_valid_delegated_token(db: AsyncSession, *, user: User) -> str:
    """Returns a currently-valid delegated Graph access token for this user,
    refreshing it first if it's expired/near-expiry. Raises
    `DelegatedTokenUnavailableError` — never fabricates or falls back to an
    app-only token — when none exists or a refresh fails."""
    if not settings.graph_configured:
        raise DelegatedTokenUnavailableError("Microsoft Graph is not configured.")

    tenant = await db.get(Tenant, user.tenant_id)
    if not user.ms_object_id or not tenant or tenant.ms_tenant_id != settings.ms_tenant_id:
        raise DelegatedTokenUnavailableError("This account is not linked to the configured Microsoft tenant.")
    cipher = _cipher()
    row = (await db.execute(select(GraphUserToken).where(GraphUserToken.user_id == user.id))).scalar_one_or_none()
    if row is None:
        raise DelegatedTokenUnavailableError(
            "No Microsoft Teams access has been granted for this account yet. "
            "Sign in again via Microsoft Entra ID and consent to Teams chat access."
        )

    now = datetime.now(timezone.utc)
    if _aware(row.expires_at) > now + timedelta(seconds=_REFRESH_SKEW_SECONDS):
        try:
            return cipher.decrypt(row.access_token.encode()).decode()
        except InvalidToken:
            raise DelegatedTokenUnavailableError("Teams token cannot be decrypted. Sign in again.") from None

    if not row.refresh_token:
        raise DelegatedTokenUnavailableError(
            "The stored Microsoft Teams access token has expired and cannot be refreshed. Sign in again."
        )

    try:
        refresh = cipher.decrypt(row.refresh_token.encode()).decode()
        result = _msal_app().acquire_token_by_refresh_token(refresh, scopes=_chat_scopes_qualified())
    except Exception:
        raise DelegatedTokenUnavailableError("Teams authorization cannot be refreshed. Sign in again.") from None
    if "access_token" not in result:
        raise DelegatedTokenUnavailableError("Teams authorization expired or was revoked. Sign in again.")

    row.access_token = cipher.encrypt(result["access_token"].encode()).decode()
    row.refresh_token = cipher.encrypt(result["refresh_token"].encode()).decode() if result.get("refresh_token") else row.refresh_token
    row.expires_at = now + timedelta(seconds=result.get("expires_in", 3600))
    await db.flush()
    return result["access_token"]
