"""Internal session token issuance/verification.

Both auth providers (Entra ID and dev) funnel into the same session token so
the rest of the application never needs to know which login path was used.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jose import JWTError, jwt

from meeting_intel.config import get_settings

settings = get_settings()


class InvalidTokenError(Exception):
    pass


def create_session_token(*, user_id: str, tenant_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expires_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_session_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc
