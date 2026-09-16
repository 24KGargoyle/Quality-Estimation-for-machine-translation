"""Async engine/session — SQLite (local/test) or Azure SQL (production).

No PostgreSQL dependency: `create_async_engine` is dialect-agnostic at this
call site, since nothing downstream (models.py, every query) uses
PostgreSQL-specific SQL any more — see docs/MIGRATION_FROM_POSTGRES.md. The
Azure SQL production path requires an async-capable driver (e.g.
`mssql+aioodbc://...`); see docs/AZURE_SETUP.md for the exact connection
string and the documented synchronous fallback if your ODBC driver stack has
no async support.
"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from meeting_intel.config import ensure_sqlite_parent_dir, get_settings

settings = get_settings()
ensure_sqlite_parent_dir(settings.resolved_database_url)

engine = create_async_engine(settings.resolved_database_url, pool_pre_ping=True, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
