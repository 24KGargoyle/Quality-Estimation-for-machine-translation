# Deployment

## Local development (exact commands used to build/verify this platform)

### 1. Database

```bash
# Postgres 16 + pgvector must be running and reachable.
sudo apt-get install -y postgresql-16-pgvector   # if not already installed
sudo service postgresql start
sudo -u postgres psql -c "CREATE USER meeting_intel WITH PASSWORD 'meeting_intel' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE meeting_intel OWNER meeting_intel;"
sudo -u postgres psql -d meeting_intel -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### 2. Backend

```bash
cd app/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY, and MS_* if using AUTH_PROVIDER=entra
alembic upgrade head
uvicorn meeting_intel.main:app --app-dir src --reload --port 8000
```

Health check: `curl http://localhost:8000/health` → `{"status":"ok", "graph_configured":..., "llm_configured":..., "auth_provider":...}`.

### 3. Frontend

```bash
cd app/frontend
npm install
cp .env.example .env.local   # NEXT_PUBLIC_API_BASE_URL, defaults to http://localhost:8000
npm run dev
```

Open `http://localhost:3000`.

### 4. Tests

```bash
cd app/backend
sudo -u postgres psql -c "CREATE DATABASE meeting_intel_test OWNER meeting_intel;"
sudo -u postgres psql -d meeting_intel_test -c "CREATE EXTENSION IF NOT EXISTS vector;"
source .venv/bin/activate
python -m pytest -q
```

## Docker Compose (local, all-in-one)

```bash
cd app
cp backend/.env.example backend/.env   # fill in secrets
docker compose up --build
```

Brings up `postgres` (pgvector image), `backend` (runs migrations on startup, then serves on
`:8000`), and `frontend` (`:3000`). See `app/docker-compose.yml`.

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

## Production notes / gaps to close before a real rollout

- **WebSocket fan-out** (`realtime/ws_manager.py`) is in-process; a multi-instance deployment
  needs a shared layer (Redis pub/sub or equivalent) so a message posted via one instance
  reaches a client connected to another.
- **Transcript storage**: raw VTT text is stored inline in `meeting_transcripts.storage_ref`
  (Postgres `TEXT`) for this scope; a production deployment should move this to blob storage
  (e.g. Azure Blob Storage, matching the Teams-native ecosystem) and store a reference instead.
- **Embeddings model**: `sentence-transformers/all-MiniLM-L6-v2` runs locally (no external API
  key), which increases the backend container's size/cold-start time. A hosted embeddings API
  can be swapped in behind `embeddings/embedder.py`'s two functions without touching callers.
- **Secrets**: use the platform's secret manager (Azure Key Vault, AWS Secrets Manager, etc.) to
  inject `SECRET_KEY`, `MS_CLIENT_SECRET`, `ANTHROPIC_API_KEY` as environment variables at
  deploy time — never bake them into the image.
- **Database migrations**: `alembic upgrade head` runs automatically on backend container start
  (see `Dockerfile` `CMD`); for a multi-instance rollout, run it once as a release step instead.
