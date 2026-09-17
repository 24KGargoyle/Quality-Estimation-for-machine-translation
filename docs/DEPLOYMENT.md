# Deployment

No Docker is used for this platform — it runs directly with SQLite (zero external database
server, local development and tests), a Python virtualenv for the backend, and Node/npm for the
frontend. **No PostgreSQL install is required anywhere** — see
`docs/MIGRATION_FROM_POSTGRES.md`. Production targets Azure SQL Database, Azure AI Search, and
Azure OpenAI; see `docs/AZURE_SETUP.md` for provisioning those.

## 1. Database (local/dev — no setup required)

```bash
# Nothing to install. SQLite is created automatically on first run/migration
# at app/backend/data/meeting_intel.db (the parent directory is created
# automatically by ensure_sqlite_parent_dir() in config.py).
```

For production, set `AZURE_SQL_CONNECTION_STRING` instead — see `docs/AZURE_SETUP.md` for the
exact connection string and the required async ODBC driver.

## 2. Backend

```bash
cd app/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY, and MS_* if using AUTH_PROVIDER=entra
alembic upgrade head
uvicorn meeting_intel.main:app --app-dir src --reload --port 8000
```

`pyproject.toml` declares `requires-python = ">=3.11"`. The full test suite (58 tests) passes on
Python 3.11 with the exact pins in `requirements.txt` — `aiosqlite` (async SQLite driver) and
`openai` (Azure OpenAI SDK) were added; `asyncpg`, `psycopg2-binary`, and any other
PostgreSQL-specific driver were removed entirely — nothing in this app connects to PostgreSQL.

Health check: `curl http://localhost:8000/health` → `{"status":"ok", "graph_configured":..., "llm_configured":..., "auth_provider":...}`.

`sentence-transformers` (used for the default local embedding provider) pulls in PyTorch — a
sizeable dependency (roughly 1-2GB on first install). Set `EMBEDDING_PROVIDER=azure_openai` (with
the `AZURE_OPENAI_*` settings) to use Azure OpenAI embeddings instead, avoiding that dependency —
see `providers.py`.

## 3. Frontend

```bash
cd app/frontend
npm install
cp .env.example .env.local   # NEXT_PUBLIC_API_BASE_URL, defaults to http://localhost:8000
npm run dev
```

Open `http://localhost:3000`. No frontend changes were needed for the PostgreSQL removal — every
API response shape (Pydantic schemas) is unchanged; only the backend's internal storage moved.

## 4. Tests

```bash
cd app/backend
source .venv/bin/activate
python -m pytest -q
```

No database server setup is required — tests run against a real, isolated, temporary SQLite file
per test session (`tests/conftest.py`), and search-layer tests run against the in-memory
`SearchProvider` (reset between tests) plus mocked HTTP for the Azure AI Search client. See
`docs/TESTING.md`.

## Configuring real Microsoft Entra ID / Graph

1. Register an app in Azure AD (see `docs/MICROSOFT_GRAPH_PERMISSIONS.md` for exact
   permissions + the required Cloud Communications application access policy).
2. Set in `app/backend/.env`: `AUTH_PROVIDER=entra`, `MS_TENANT_ID`, `MS_CLIENT_ID`,
   `MS_CLIENT_SECRET`, `MS_REDIRECT_URI`.
3. No code changes are required — `graph_configured` flips to `true` and `/health` reflects it;
   the frontend's Settings page surfaces the same status.

## Configuring the LLM and embeddings

- **Anthropic (default)**: set `ANTHROPIC_API_KEY` in `app/backend/.env`. `LLM_MODEL` defaults to
  `claude-sonnet-5`.
- **Azure OpenAI**: set `LLM_PROVIDER=azure_openai` and/or `EMBEDDING_PROVIDER=azure_openai`,
  plus the `AZURE_OPENAI_*` settings — see `docs/AZURE_SETUP.md`.

Without credentials for whichever provider is selected, chat/discussion/decision endpoints
degrade gracefully (explicit "AI model is not configured" message) rather than crashing or
fabricating answers.

## Historical Meeting Data Import

No setup required for local dev — raw files land under `./data/historical_blobs` by default
(`FILE_STORAGE=local`). For production, set `FILE_STORAGE=azure_blob` and
`AZURE_STORAGE_CONTAINER_SAS_URL` — see `docs/AZURE_SETUP.md` and `docs/HISTORICAL_IMPORT.md`.
Import jobs run as background `asyncio` tasks inside the backend process (no separate worker); an
in-flight job is lost if the process restarts mid-batch — acceptable for this environment's scale,
but replace with a real task queue before relying on this for very large/critical batch imports in
production.

## Configuring search (RAG)

- **In-memory (default, `SEARCH_PROVIDER=memory`)**: no setup, real working hybrid search for
  local dev/tests — **not** Azure AI Search, never presented as such.
- **Azure AI Search (`SEARCH_PROVIDER=azure_search`)**: set `AZURE_SEARCH_ENDPOINT`,
  `AZURE_SEARCH_API_KEY`, `AZURE_SEARCH_INDEX` — see `docs/AZURE_SETUP.md`. The index is created/
  updated automatically (`ensure_index()`) on first write.

## Running as long-lived services (production-ish, still no Docker)

- **Backend**: run `alembic upgrade head` as a release step, then serve with
  `uvicorn meeting_intel.main:app --host 0.0.0.0 --port 8000` (drop `--reload`) under a process
  supervisor — `systemd`, `supervisord`, or a process manager like `pm2`. Put a reverse proxy
  (nginx, Caddy) in front for TLS.
- **Frontend**: `npm run build && npm run start` (Next.js's own production server), also under a
  supervisor, behind the same reverse proxy.
- **Database**: Azure SQL Database (`AZURE_SQL_CONNECTION_STRING`) rather than the local SQLite
  file used above — see `docs/AZURE_SETUP.md` for the connection string format and the required
  async-capable ODBC driver.
- **Search**: Azure AI Search (`SEARCH_PROVIDER=azure_search`) rather than the in-memory dev
  provider — see `docs/AZURE_SETUP.md`.

## Production notes / gaps to close before a real rollout

- **WebSocket fan-out** (`realtime/ws_manager.py`) is in-process; running more than one backend
  instance needs a shared layer (Redis pub/sub or equivalent) so a message posted via one
  instance reaches a client connected to another.
- **Transcript storage**: raw VTT text is stored inline in `meeting_transcripts.storage_ref` for
  this scope; a production deployment should move this to blob storage (e.g. Azure Blob Storage,
  matching the Teams-native ecosystem) and store a reference instead.
- **Embeddings model**: `sentence-transformers/all-MiniLM-L6-v2` runs locally (no external API
  key) by default, at the cost of the PyTorch dependency size/install time noted above. Azure
  OpenAI embeddings are a real, alternate, drop-in `EmbeddingProvider` — see `providers.py`.
- **Azure SQL / Azure AI Search / Azure OpenAI**: real implementations exist behind their
  respective abstractions but have **not been live-tested against actual Azure resources** in
  this environment (none are available here) — see `docs/AZURE_SETUP.md` and the final
  implementation report's stated limitations. Provision the resources, set the corresponding
  environment variables, and run the app's own health/smoke checks against them before relying on
  this in production.
- **Secrets**: use the platform's secret manager (Azure Key Vault, AWS Secrets Manager, a `.env`
  injected by the supervisor, etc.) to provide `SECRET_KEY`, `MS_CLIENT_SECRET`,
  `ANTHROPIC_API_KEY`/`AZURE_OPENAI_API_KEY`/`AZURE_SEARCH_API_KEY`,
  `AZURE_SQL_CONNECTION_STRING` as environment variables at deploy time — never commit them.
- **Database migrations**: run `alembic upgrade head` as an explicit release step before starting
  new backend processes, rather than automatically on every process start, once there's more than
  one backend instance.
