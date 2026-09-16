# Migration from PostgreSQL

**Historical document.** This describes a completed refactor: PostgreSQL has been fully removed
from this application. Every reference to PostgreSQL below is historical context explaining what
changed and why — none of it describes the current, executable configuration. The current stack
is documented in `docs/ARCHITECTURE.md`, `docs/DATABASE.md`, `docs/RAG_ARCHITECTURE.md`, and
`docs/AZURE_SETUP.md`.

## Why

The original implementation used a single plain PostgreSQL database for both relational data and
full-text search, with vector similarity computed in Python (to avoid the `pgvector` extension,
which has no plain installer on Windows). This refactor replaces PostgreSQL entirely with:

- **Azure SQL Database** (production) / **SQLite** (local dev, tests) for relational/transactional
  data.
- **Azure AI Search** (production) / an honestly-labeled **in-memory search provider** (local dev,
  tests) for keyword, vector, hybrid, and semantic search over transcript chunks.

## What changed, table by table / component by component

| Old (PostgreSQL) | New | Notes |
|---|---|---|
| `postgresql+asyncpg://` connection, `DATABASE_URL` | `sqlite+aiosqlite://` (dev/test default) or `AZURE_SQL_CONNECTION_STRING` (production), resolved via `Settings.resolved_database_url` | `create_async_engine` is dialect-agnostic; no code downstream depends on PostgreSQL-specific SQL. |
| `transcript_chunks` table (with a generated `tsv` column + GIN index for keyword search, `embedding` as a JSON column) | `retrieval.search_provider.IndexableChunk`/`SearchHit`, indexed via `SearchProvider.index_chunks()` — lives outside the relational database entirely | Chunks and embeddings are never stored in Azure SQL/SQLite. |
| PostgreSQL full-text search: `tsv @@ plainto_tsquery(...)`, ranked by `ts_rank_cd` | Azure AI Search's native full-text/semantic ranking (production), or in-process word-overlap scoring (dev/test) | See `retrieval/azure_search.py: keyword_search`/`hybrid_search`, `retrieval/memory_search.py: _keyword_score`. |
| Vector similarity computed in Python (numpy cosine over `transcript_chunks.embedding` JSON, loaded from Postgres) | Azure AI Search native vector search (HNSW/cosine, production), or the same numpy cosine logic now operating over an in-process store (dev/test) | The RRF fusion algorithm itself is unchanged — only where the candidate chunks are loaded from moved. |
| Alembic migration adding the `tsv` generated column + GIN index (PostgreSQL-specific raw SQL) | **Deleted.** No replacement migration — full-text search is no longer a database concern. | |
| `sa.text('now()')` (PostgreSQL server-side default literal) in the initial migration | `sa.func.now()` (dialect-portable — SQLAlchemy renders the correct literal per backend) | |
| `ai_sources.chunk_id` as a foreign key to `transcript_chunks.id` | `ai_sources.chunk_id` as a plain indexed string (no FK) — the chunk it references now lives in the `SearchProvider`, not this database | |
| `psycopg2`/`asyncpg` dependencies | `aiosqlite` (dev/test) added; an async ODBC driver documented (not installed — see `docs/AZURE_SETUP.md`) for Azure SQL production use | `psycopg2`/`asyncpg` removed from `requirements.txt` entirely. |
| `DATABASE_URL=postgresql://...`, `POSTGRES_HOST`/`PORT`/`DB`/`USER`/`PASSWORD` env vars | `DATABASE_URL=sqlite+aiosqlite:///./data/meeting_intel.db` (dev default), `AZURE_SQL_CONNECTION_STRING` (production) | See `app/backend/.env.example`. |
| Postgres install step in `docs/DEPLOYMENT.md`/`docs/TESTING.md` (`apt-get install postgresql-16`, `CREATE DATABASE`, etc.) | No install step — SQLite is created automatically; Azure SQL is a managed Azure resource, provisioned per `docs/AZURE_SETUP.md` | |

## What did NOT change

- The RRF (Reciprocal Rank Fusion) hybrid-ranking algorithm itself — only its storage backend.
- The chunking/embedding pipeline (`ingestion/chunker.py`, embedding generation) — unchanged
  except that its output now goes to a `SearchProvider` instead of an ORM insert.
- Every business-logic layer above the database/search boundary: agents, routers, authorization,
  Graph integration, Teams conversation delivery, WebSocket real-time updates, the frontend. None
  of these depended on PostgreSQL directly — they went through the ORM (for relational data) or
  `retrieval/hybrid_search.py` (for search), both of which absorbed the change.
- Citation/grounding behavior: citations are still mapped back to the exact retrieved chunk's
  metadata (speaker, timestamp), never fabricated by the LLM.

## Security fixes made alongside this refactor

Not strictly part of the PostgreSQL removal, but found and fixed during the same audit pass (see
the final implementation report for full detail):

1. Entra OAuth `state` is now server-persisted (`oauth_states` table), single-use, and validated
   on callback — previously accepted from the client and never checked (a CSRF vulnerability).
2. Session logout now actually revokes the JWT (`revoked_tokens` table + the token's `jti`
   claim) — previously there was no server-side logout at all.
3. Sharing a group-sourced AI message now requires membership in the *source* group, not only the
   destination group — previously any tenant user could re-share another group's AI answer.

## Verifying zero PostgreSQL dependency

A repository-wide case-insensitive search for `postgres`, `postgresql`, `pgvector`, `psycopg`,
`psycopg2`, `asyncpg`, `CREATE EXTENSION`, `tsvector`, `to_tsvector`, `plainto_tsquery`, and
`websearch_to_tsquery` across `app/backend/src/`, `app/backend/alembic/`, `app/backend/tests/`,
`app/backend/requirements.txt`, `app/backend/.env.example`, and `app/frontend/` returns **zero
runtime/executable matches** — the only hits anywhere in the codebase are prose comments and
docstrings explicitly describing this migration (e.g. "PostgreSQL-free refactor", pointers to
this document), and this document itself. See the final implementation report for the exact scan
output.
