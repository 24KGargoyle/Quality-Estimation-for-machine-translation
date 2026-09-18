import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Real SQLite (async, via aiosqlite) — zero external database server required.
# One file per test session, recreated fresh each run. This replaces the
# previous PostgreSQL test database entirely; see docs/MIGRATION_FROM_POSTGRES.md.
_TEST_DB_DIR = tempfile.TemporaryDirectory()
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{_TEST_DB_DIR.name}/test.db"

os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("AUTH_PROVIDER", "dev")
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ["SEARCH_PROVIDER"] = "memory"
os.environ["EMBEDDING_PROVIDER"] = "local"
os.environ["LLM_PROVIDER"] = "anthropic"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["MS_TENANT_ID"] = ""
os.environ["MS_CLIENT_ID"] = ""
os.environ["MS_CLIENT_SECRET"] = ""
os.environ["WEB_RESEARCH_PROVIDER"] = "none"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"


@pytest.fixture(scope="session", autouse=True)
def _deny_live_network():
    """Tests may use mocked HTTP transports, never actual network sockets."""
    import socket
    patch = pytest.MonkeyPatch()
    original_connect = socket.socket.connect
    def denied(sock, address, *args, **kwargs):
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return original_connect(sock, address)
        raise AssertionError("Live network connections are forbidden in tests")
    import asyncio
    async def denied_async(*args, **kwargs):
        raise AssertionError("Live network connections are forbidden in tests")
    patch.setattr(asyncio.BaseEventLoop, "create_connection", denied_async)
    patch.setattr(socket.socket, "connect", denied)
    patch.setattr(socket.socket, "connect_ex", denied)
    patch.setattr(socket, "create_connection", denied)
    yield
    patch.undo()


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
    _TEST_DB_DIR.cleanup()


@pytest_asyncio.fixture(autouse=True)
async def _clean_tables():
    """Delete all rows between tests for isolation, without recreating the
    schema each time. Also resets the in-memory search provider, which holds
    process-local state the database truncation below knows nothing about."""
    from meeting_intel.retrieval.memory_search import get_memory_provider

    get_memory_provider().reset()

    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        from sqlalchemy import text

        tables = [
            "graph_user_tokens", "revoked_tokens", "oauth_states", "audit_log", "action_items", "decisions", "discussions",
            "feedback", "ai_sources", "ai_responses", "messages", "conversation_members", "conversations",
            "group_members", "groups", "imported_file_results", "historical_documents",
            "historical_import_jobs", "meeting_transcripts", "meeting_participants", "meetings",
            "teams_mappings", "users", "tenants",
        ]
        for table in tables:
            await conn.execute(text(f"DELETE FROM {table}"))
    await engine.dispose()
    yield
    # Background imports use the application's engine rather than the client
    # fixture's engine. Release its SQLite handles before deleting the test DB.
    from meeting_intel.db.session import engine as application_engine
    await application_engine.dispose()


@pytest_asyncio.fixture
async def client():
    """Fresh engine/sessionmaker bound to this test's running event loop,
    overriding the app's module-level `get_db` dependency."""
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
