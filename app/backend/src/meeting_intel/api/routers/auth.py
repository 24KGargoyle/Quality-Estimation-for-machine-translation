from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.auth.deps import RequestContext, get_current_context
from meeting_intel.auth.dev import DevAuthDisabledError, dev_login
from meeting_intel.auth.entra import GraphNotConfiguredError, acquire_token_by_auth_code, get_login_url
from meeting_intel.api.schemas import DevLoginRequest, EntraCallbackRequest, LoginUrlResponse, TokenResponse
from meeting_intel.config import get_settings
from meeting_intel.db.models import Tenant, User, UserRole
from meeting_intel.db.session import get_db
from meeting_intel.security.jwt import create_session_token
from meeting_intel.security.session_security import consume_oauth_state, create_oauth_state, revoke_token

router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()


def _token_response(user: User) -> TokenResponse:
    token = create_session_token(user_id=user.id, tenant_id=user.tenant_id, role=user.role.value)
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        display_name=user.display_name,
        tenant_id=user.tenant_id,
        role=user.role.value,
    )


@router.get("/provider")
async def auth_provider() -> dict:
    return {"provider": settings.auth_provider}


@router.post("/dev-login", response_model=TokenResponse)
async def dev_login_endpoint(payload: DevLoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    if settings.auth_provider != "dev":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dev auth is not enabled")
    try:
        user = await dev_login(
            db, email=payload.email, display_name=payload.display_name, tenant_name=payload.tenant_name
        )
    except DevAuthDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return _token_response(user)


@router.get("/entra/login-url", response_model=LoginUrlResponse)
async def entra_login_url(db: AsyncSession = Depends(get_db)) -> LoginUrlResponse:
    if settings.auth_provider != "entra":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Entra auth is not the active provider")
    try:
        # Persisted server-side and required back on the callback below, so a
        # callback can never be accepted unless this server actually issued
        # the login it claims to complete (CSRF / login-injection protection).
        url = get_login_url(state=await create_oauth_state(db))
    except GraphNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return LoginUrlResponse(login_url=url)


@router.post("/entra/callback", response_model=TokenResponse)
async def entra_callback(payload: EntraCallbackRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    if settings.auth_provider != "entra":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Entra auth is not the active provider")
    if not await consume_oauth_state(db, payload.state):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired login state")
    try:
        result = await acquire_token_by_auth_code(payload.code)
    except GraphNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    profile = result["profile"]
    ms_object_id = profile["id"]
    email = profile.get("mail") or profile.get("userPrincipalName")
    display_name = profile.get("displayName", email)
    ms_tenant_id = result["id_token_claims"].get("tid")

    tenant = (await db.execute(select(Tenant).where(Tenant.ms_tenant_id == ms_tenant_id))).scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(name=ms_tenant_id, ms_tenant_id=ms_tenant_id)
        db.add(tenant)
        await db.flush()

    user = (await db.execute(select(User).where(User.ms_object_id == ms_object_id))).scalar_one_or_none()
    if user is None:
        is_first_user = (
            await db.execute(select(User).where(User.tenant_id == tenant.id))
        ).first() is None
        user = User(
            tenant_id=tenant.id,
            email=email,
            display_name=display_name,
            ms_object_id=ms_object_id,
            role=UserRole.admin if is_first_user else UserRole.member,
        )
        db.add(user)
        await db.flush()
    await db.commit()

    return _token_response(user)


@router.post("/logout")
async def logout(
    ctx: RequestContext = Depends(get_current_context), db: AsyncSession = Depends(get_db)
) -> dict:
    """Revokes this session's token immediately (rather than leaving it valid
    until JWT_EXPIRES_MINUTES naturally elapses) — the client should also
    discard the token, but a copied/leaked token stops working the moment
    the legitimate user logs out, not up to 12 hours later."""
    await revoke_token(db, jti=ctx.jti, expires_at=ctx.expires_at)
    return {"status": "logged_out"}
