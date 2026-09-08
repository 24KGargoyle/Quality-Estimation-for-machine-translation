# Deployment

No Docker is used for this platform — it runs directly with a local Postgres install, a Python
virtualenv for the backend, and Node/npm for the frontend. These are the exact commands used to
build and verify it.

## 1. Database

```bash
# Postgres 16 + pgvector must be running and reachable.
sudo apt-get install -y postgresql-16-pgvector   # if not already installed
sudo service postgresql start
sudo -u postgres psql -c "CREATE USER meeting_intel WITH PASSWORD 'meeting_intel' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE meeting_intel OWNER meeting_intel;"
sudo -u postgres psql -d meeting_intel -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

On macOS: `brew install postgresql@16 pgvector` (or build pgvector from source against a
Postgres.app install). On Windows: run the above under WSL2.

## 2. Backend

```bash
cd app/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY, and MS_* if using AUTH_PROVIDER=entra
alembic upgrade head
uvicorn meeting_intel.main:app --app-dir src --reload --port 8000
```

`pyproject.toml` declares `requires-python = ">=3.11"`. The full test suite (30 tests) was
verified passing on both Python 3.11.15 and Python 3.14.7 with the exact pins in
`requirements.txt` — `asyncpg`, `pydantic`/`pydantic-core`, `pydantic-settings`, and `sqlalchemy`
are pinned at versions confirmed to ship 3.14 wheels/support (older pins built cleanly on 3.11
but failed to build from source on 3.14, since no prebuilt wheel existed for those versions
there). `psycopg2-binary` and `aiosqlite` were removed — the app only ever uses the async
`asyncpg` driver, and those two packages were unused dead weight (the former also has no 3.14
wheel for the pinned version, which is what surfaced the issue).

Health check: `curl http://localhost:8000/health` → `{"status":"ok", "graph_configured":..., "llm_configured":..., "auth_provider":...}`.

`sentence-transformers` (used for local embeddings) pulls in PyTorch — a sizeable dependency
(roughly 1-2GB on first install). If that's a problem, `embeddings/embedder.py`'s two functions
(`embed_texts`/`embed_query`) can be swapped for a hosted embeddings API call without touching
any caller.

## 3. Frontend

```bash
cd app/frontend
npm install
cp .env.example .env.local   # NEXT_PUBLIC_API_BASE_URL, defaults to http://localhost:8000
npm run dev
```

Open `http://localhost:3000`.

## 4. Tests

```bash
cd app/backend
sudo -u postgres psql -c "CREATE DATABASE meeting_intel_test OWNER meeting_intel;"
sudo -u postgres psql -d meeting_intel_test -c "CREATE EXTENSION IF NOT EXISTS vector;"
source .venv/bin/activate
python -m pytest -q
```

## Configuring real Microsoft Entra ID / Graph

1. Register an app in Azure AD (see `docs/MICROSOFT_GRAPH_PERMISSIONS.md` for exact
   permissions + the required Cloud Communications application access policy).
2. Set in `app/backend/.env`: `AUTH_PROVIDER=entra`, `MS_TENANT_ID`, `MS_CLIENT_ID`,
   `MS_CLIENT_SECRET`, `MS_REDIRECT_URI`.
3. No code changes are required — `graph_configured` flips to `true` and `/health` reflects it;
   the frontend's Settings page surfaces the same status.

## Configuring the LLM

Set `ANTHROPIC_API_KEY` in `app/backend/.env`. `LLM_MODEL` defaults to `claude-sonnet-5`.
Without a key, chat/discussion/decision endpoints degrade gracefully (explicit "AI model is not
configured" message) rather than crashing or fabricating answers — see `IMPLEMENTATION_REPORT.md`.

## Running as long-lived services (production-ish, still no Docker)

- **Backend**: run `alembic upgrade head` as a release step, then serve with
  `uvicorn meeting_intel.main:app --host 0.0.0.0 --port 8000` (drop `--reload`) under a process
  supervisor — `systemd`, `supervisord`, or a process manager like `pm2`. Put a reverse proxy
  (nginx, Caddy) in front for TLS.
- **Frontend**: `npm run build && npm run start` (Next.js's own production server), also under a
  supervisor, behind the same reverse proxy.
- **Database**: a managed Postgres instance with the `pgvector` extension available (e.g. Azure
  Database for PostgreSQL, Amazon RDS with the `pgvector` extension enabled, or a self-managed
  instance) rather than the local install used above.

## Production notes / gaps to close before a real rollout

- **WebSocket fan-out** (`realtime/ws_manager.py`) is in-process; running more than one backend
  instance needs a shared layer (Redis pub/sub or equivalent) so a message posted via one
  instance reaches a client connected to another.
- **Transcript storage**: raw VTT text is stored inline in `meeting_transcripts.storage_ref`
  (Postgres `TEXT`) for this scope; a production deployment should move this to blob storage
  (e.g. Azure Blob Storage, matching the Teams-native ecosystem) and store a reference instead.
- **Embeddings model**: `sentence-transformers/all-MiniLM-L6-v2` runs locally (no external API
  key), at the cost of the PyTorch dependency size/install time noted above. A hosted embeddings
  API can be swapped in behind `embeddings/embedder.py`'s two functions without touching callers.
- **Secrets**: use the platform's secret manager (Azure Key Vault, AWS Secrets Manager, a `.env`
  injected by the supervisor, etc.) to provide `SECRET_KEY`, `MS_CLIENT_SECRET`,
  `ANTHROPIC_API_KEY` as environment variables at deploy time — never commit them.
- **Database migrations**: run `alembic upgrade head` as an explicit release step before starting
  new backend processes, rather than automatically on every process start, once there's more than
  one backend instance.
