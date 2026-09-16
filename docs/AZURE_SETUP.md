# Azure Setup

This platform's production targets are **Azure SQL Database**, **Azure AI Search**, and **Azure
OpenAI**, plus the pre-existing **Microsoft Entra ID** / Graph integration. None of these Azure
resources are available in this development environment — this document describes what to
provision and how to point the app at it. **No PostgreSQL resource is needed anywhere.**

Per this refactor's explicit constraint: the app implements the correct interfaces, validates
configuration, and fails loudly (a clear "not configured" error) rather than fabricating Azure
behavior locally. Nothing in this codebase claims to have been live-tested against a real Azure
resource — see each section's "Verified in this environment" note.

## 1. Azure SQL Database (relational/transactional data)

Replaces PostgreSQL as the store for users, tenants, conversations, messages, groups, group
members, meeting metadata, feedback, decisions, action items, Teams bindings, application
configuration, and audit records. **Never** stores vector embeddings or transcript chunks — those
live in Azure AI Search.

1. Create an Azure SQL Database (Basic/Standard tier is sufficient for this workload).
2. Create a login/user with `db_owner` on that database (or a more restricted role covering
   `CREATE TABLE`/`ALTER`/`INSERT`/`UPDATE`/`DELETE`/`SELECT` for migrations to run).
3. Set `AZURE_SQL_CONNECTION_STRING` in `app/backend/.env`, e.g.:
   ```
   AZURE_SQL_CONNECTION_STRING=mssql+aioodbc://<user>:<password>@<server>.database.windows.net:1433/<database>?driver=ODBC+Driver+18+for+SQL+Server
   ```
   This requires the `aioodbc` Python package and the Microsoft ODBC Driver 18 for SQL Server
   installed on the host — neither is installed in this development environment (no async ODBC
   stack was available to verify). If your deployment target has no working async ODBC driver,
   `mssql+pyodbc` (synchronous) is the documented fallback, which requires converting
   `db/session.py`'s `create_async_engine`/`AsyncSession` calls to their synchronous equivalents
   — not done here, since the async path is the one this app is built around.
4. Run `alembic upgrade head` against it — the migration is dialect-portable (no PostgreSQL types,
   no raw `tsvector`/GIN SQL, `sa.func.now()` instead of a Postgres-specific literal).

**Verified in this environment**: the SQLAlchemy async engine and every model/query in this app
are dialect-generic (checked by running the full test suite and `alembic upgrade head` against
SQLite). The Azure SQL connection string itself has **not** been exercised against a real Azure
SQL Database here — no Azure subscription is available.

## 2. Azure AI Search (transcript search / RAG retrieval)

Replaces PostgreSQL full-text search and the prior Python/numpy vector similarity. Keyword,
vector, hybrid, and semantic search over meeting transcript chunks.

1. Create an Azure AI Search service (Basic tier or above — semantic ranking requires a paid
   tier; the free tier does not support it).
2. In the Azure Portal, enable **Semantic ranker** on the service if not already on (Basic tier
   includes a limited free allotment).
3. Set in `app/backend/.env`:
   ```
   SEARCH_PROVIDER=azure_search
   AZURE_SEARCH_ENDPOINT=https://<service-name>.search.windows.net
   AZURE_SEARCH_API_KEY=<admin-key>
   AZURE_SEARCH_INDEX=transcript-chunks
   AZURE_SEARCH_SEMANTIC_CONFIG=default
   ```
4. No manual index creation is needed — `AzureAISearchProvider.ensure_index()` creates/updates
   the index (see `docs/RAG_ARCHITECTURE.md` for the exact field schema) automatically before the
   first document write. Vector `dimensions` in that schema are read from whichever embedding
   provider/model is configured (§3 below) — **never hardcoded** — so re-provisioning the index
   after changing embedding models re-creates it with the correct dimension.

**Verified in this environment**: `retrieval/azure_search.py`'s REST request/response shapes,
index schema, mandatory tenant/meeting filter construction, and OData escaping are unit-tested
against mocked HTTP (`tests/unit/test_azure_search.py`). **No live Azure AI Search service has
been queried from this codebase** — no Azure subscription is available here.

## 3. Azure OpenAI (LLM + embeddings)

Optional alternate provider to the default (working today) Anthropic Claude LLM and local
sentence-transformers embeddings. Both are selected independently:

```
LLM_PROVIDER=azure_openai
EMBEDDING_PROVIDER=azure_openai

AZURE_OPENAI_ENDPOINT=https://<resource-name>.openai.azure.com
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_CHAT_DEPLOYMENT=<your-chat-deployment-name>
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=<your-embedding-deployment-name>
AZURE_OPENAI_EMBEDDING_DIMENSIONS=<actual output size of that deployment, e.g. 1536>
```

1. Create an Azure OpenAI resource and deploy a chat model (e.g. `gpt-4o`) and an embedding model
   (e.g. `text-embedding-3-small`, 1536 dimensions, or `text-embedding-3-large`, 3072 dimensions).
2. `AZURE_OPENAI_EMBEDDING_DIMENSIONS` **must** match the real output size of the deployed
   embedding model exactly — this is never inferred from the deployment name (an arbitrary
   alias); `providers.AzureOpenAIEmbeddingProvider` validates the returned vector's length against
   this setting and raises rather than silently indexing mismatched vectors.
3. You can mix providers — e.g. `LLM_PROVIDER=anthropic` with `EMBEDDING_PROVIDER=azure_openai` —
   since each is selected independently via `providers.get_llm_provider()`/`get_embedding_provider()`.

**Verified in this environment**: `providers.AzureOpenAILLMProvider`/`AzureOpenAIEmbeddingProvider`
use the official `openai` Python SDK's `AsyncAzureOpenAI`/`AzureOpenAI` clients exactly as
documented, and raise a clear `LLMNotConfiguredError`/equivalent when required settings are
missing. **No live Azure OpenAI call has been made from this codebase** — no API key is available
in this environment.

## 4. Microsoft Entra ID / Graph (unchanged by this refactor)

See `docs/MICROSOFT_GRAPH_PERMISSIONS.md` for the app registration and permissions required for
Teams meeting/transcript/chat integration — this was not affected by the PostgreSQL removal.

## Summary of required environment variables

See `app/backend/.env.example` for the complete, current list with inline documentation. At
minimum for a full production deployment: `AZURE_SQL_CONNECTION_STRING`,
`AZURE_SEARCH_ENDPOINT`/`AZURE_SEARCH_API_KEY`/`AZURE_SEARCH_INDEX`, `AZURE_OPENAI_ENDPOINT`/
`AZURE_OPENAI_API_KEY`/`AZURE_OPENAI_CHAT_DEPLOYMENT`/`AZURE_OPENAI_EMBEDDING_DEPLOYMENT`/
`AZURE_OPENAI_EMBEDDING_DIMENSIONS`, `MS_TENANT_ID`/`MS_CLIENT_ID`/`MS_CLIENT_SECRET`/
`MS_REDIRECT_URI`, `SECRET_KEY`. None of these are committed anywhere in this repository — never
commit real secrets.
