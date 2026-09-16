from datetime import datetime, timezone
import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.db.models import User
from meeting_intel.db.session import get_db
from meeting_intel.security.jwt import InvalidTokenError, decode_session_token
from meeting_intel.security.session_security import is_token_revoked


class RequestContext:
    """Carries the caller's identity + a request id for logging/audit."""

    def __init__(self, user: User, request_id: str, jti: str, expires_at: datetime):
        self.user = user
        self.tenant_id = user.tenant_id
        self.request_id = request_id
        self.jti = jti
        self.expires_at = expires_at


async def get_current_context(
    authorization: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> RequestContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1]
    try:
        claims = decode_session_token(token)
    except InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session")

    jti = claims.get("jti")
    if not jti or await is_token_revoked(db, jti):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been logged out")

    user = (await db.execute(select(User).where(User.id == claims["sub"]))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    if user.tenant_id != claims.get("tenant_id"):
        # Defense in depth: token tenant must always match the live row's tenant.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tenant mismatch")

    request_id = x_request_id or str(uuid.uuid4())
    expires_at = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
    return RequestContext(user=user, request_id=request_id, jti=jti, expires_at=expires_at)
