"""Development-only auth provider.

Used when `AUTH_PROVIDER=dev`. This exists solely so the platform can be
exercised end-to-end (login -> meeting -> chat -> feedback -> groups) without
a live Microsoft Entra ID tenant, which this environment does not have. It
refuses to operate when `APP_ENV=production` regardless of `AUTH_PROVIDER`,
so it can never become a silent backdoor in a real deployment.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.config import get_settings
from meeting_intel.db.models import Tenant, User, UserRole

settings = get_settings()


class DevAuthDisabledError(Exception):
    pass


async def dev_login(db: AsyncSession, *, email: str, display_name: str, tenant_name: str) -> User:
    if settings.app_env == "production":
        raise DevAuthDisabledError("Dev auth is disabled when APP_ENV=production.")

    tenant = (await db.execute(select(Tenant).where(Tenant.name == tenant_name))).scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(name=tenant_name)
        db.add(tenant)
        await db.flush()

    user = (
        await db.execute(select(User).where(User.tenant_id == tenant.id, User.email == email))
    ).scalar_one_or_none()
    if user is None:
        user = User(
            tenant_id=tenant.id,
            email=email,
            display_name=display_name,
            role=UserRole.admin if (await db.execute(select(User).where(User.tenant_id == tenant.id))).first() is None else UserRole.member,
        )
        db.add(user)
        await db.flush()

    await db.commit()
    return user
