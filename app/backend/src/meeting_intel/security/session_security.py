"""OAuth login-state CSRF protection and session token revocation (logout).

Both use the relational database (not an in-memory store) so they work
correctly across multiple worker processes and survive a restart during the
brief window a user is on Microsoft's login page.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.db.models import OAuthState, RevokedToken


def _aware(value: datetime) -> datetime:
    # SQLite has no native timezone-aware storage; normalize on read so
    # comparisons against `datetime.now(timezone.utc)` never raise.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def create_oauth_state(db: AsyncSession, *, ttl_seconds: int = 600) -> str:
    state = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    await db.execute(delete(OAuthState).where(OAuthState.expires_at < now))  # opportunistic cleanup
    db.add(OAuthState(state=state, expires_at=now + timedelta(seconds=ttl_seconds)))
    await db.commit()
    return state


async def consume_oauth_state(db: AsyncSession, state: str) -> bool:
    """True iff `state` was issued by create_oauth_state and not yet used or
    expired. Always single-use: deleted whether valid or not, so a
    leaked/guessed state can never be replayed after one attempt."""
    row = (await db.execute(select(OAuthState).where(OAuthState.state == state))).scalar_one_or_none()
    if row is not None:
        await db.execute(delete(OAuthState).where(OAuthState.state == state))
        await db.commit()
    if row is None:
        return False
    return _aware(row.expires_at) >= datetime.now(timezone.utc)


async def revoke_token(db: AsyncSession, *, jti: str, expires_at: datetime) -> None:
    db.add(RevokedToken(jti=jti, expires_at=expires_at))
    await db.commit()


async def is_token_revoked(db: AsyncSession, jti: str) -> bool:
    row = (await db.execute(select(RevokedToken).where(RevokedToken.jti == jti))).scalar_one_or_none()
    return row is not None
