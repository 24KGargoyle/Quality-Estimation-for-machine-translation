import os
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parent.parent
TEST_DATABASE_URL = "postgresql+asyncpg://meeting_intel:meeting_intel@localhost:5432/meeting_intel_test"

os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("AUTH_PROVIDER", "dev")
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("SECRET_KEY", "test-secret")


@pytest.fixture(scope="session", autouse=True)
def _run_migrations():
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_ROOT),
        env=env,
        check=True,
    )
    yield


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables():
    """Truncate all tables between tests for isolation, without recreating the schema each time."""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        tables = [
            "audit_log", "action_items", "decisions", "discussions", "feedback", "ai_sources",
            "ai_responses", "messages", "conversation_members", "conversations", "group_members",
            "groups", "transcript_chunks", "meeting_transcripts", "meeting_participants", "meetings",
            "teams_mappings", "users", "tenants",
        ]
        await conn.execute(text(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE"))
    await engine.dispose()
    yield


@pytest_asyncio.fixture
async def client():
    """Fresh engine/sessionmaker bound to this test's running event loop,
    overriding the app's module-level `get_db` dependency. Avoids reusing
    asyncpg connections across event loop instances between tests."""
    from meeting_intel.db.session import get_db
    from meeting_intel.main import app

    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)
    await engine.dispose()


async def dev_login(client: AsyncClient, *, email: str, display_name: str, tenant_name: str) -> str:
    resp = await client.post(
        "/api/auth/dev-login",
        json={"email": email, "display_name": display_name, "tenant_name": tenant_name},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


SAMPLE_VTT = """WEBVTT

00:00:00.000 --> 00:00:10.000
<v Chetan Kumar>We should confirm whether CrewAI is a mandatory client requirement before changing the architecture.</v>

00:00:10.500 --> 00:00:20.000
<v Ravi Shah>I think the existing architecture is sufficient for now.</v>

00:00:20.500 --> 00:00:35.000
<v Chetan Kumar>Agreed, but let's check with the client just to be safe about CrewAI.</v>
"""
