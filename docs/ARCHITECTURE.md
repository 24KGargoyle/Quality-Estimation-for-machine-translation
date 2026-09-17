# Architecture

See `ARCHITECTURE_ASSESSMENT.md` at the repo root for the original pre-implementation assessment,
and `docs/MIGRATION_FROM_POSTGRES.md` for what changed in the PostgreSQL-removal refactor. This
document describes the system as built today — **no PostgreSQL, no pgvector, anywhere**.

## Component overview

```
                         ┌─────────────────────────┐
                         │   Next.js frontend       │
                         │   (app/frontend)         │
                         └────────────┬─────────────┘
                                      │ REST + WebSocket
                         ┌────────────▼─────────────┐
                         │   FastAPI backend         │
                         │   (app/backend)           │
                         │                           │
   ┌──────────────┐      │  Auth (Entra/dev) ─ JWT  │      ┌───────────────────┐
   │ Microsoft     │◄────┤  Graph client            │      │ LLM provider       │
   │ Graph API     │      │  Ingestion pipeline      │─────►│ (Anthropic /       │
   └──────────────┘      │  SearchProvider-backed    │      │  Azure OpenAI)     │
                         │   retrieval                │      └───────────────────┘
                         │  Agents (router/answer/   │      ┌───────────────────┐
                         │   discussion/decision)    │─────►│ Embedding provider │
                         │  Conversation providers   │      │ (local /           │
                         │  WebSocket manager        │      │  Azure OpenAI)     │
                         └──────┬─────────────┬──────┘      └───────────────────┘
                                │             │
                    ┌───────────▼───┐   ┌─────▼──────────────────┐
                    │ SQLite (dev)/ │   │ SearchProvider          │
                    │ Azure SQL     │   │  - InMemorySearchProvider│
                    │ (production)  │   │    (dev/test, NOT Azure) │
                    │ relational    │   │  - AzureAISearchProvider │
                    │ app data      │   │    (keyword+vector+      │
                    │               │   │     semantic hybrid)     │
                    └───────────────┘   └─────────────────────────┘
```

## Directory layout

```
app/
  backend/
    src/meeting_intel/
      auth/          Entra ID (MSAL) + dev auth providers, session deps
      graph/          Microsoft Graph client (meetings, transcripts, chat messages)
      ingestion/      VTT transcript parsing, chunking, indexing pipeline; parsers/ (Word/Excel/
                      PDF/PowerPoint/CSV/text parsers + ParserFactory), historical_import.py
                      (batch import job pipeline), meeting_association.py — see
                      docs/HISTORICAL_IMPORT.md
      storage/        BlobStorage abstraction for historical-import raw files (local disk / Azure Blob)
      providers.py    LLMProvider/EmbeddingProvider abstractions (Anthropic/local + Azure OpenAI)
      llm/            Anthropic client wrapper (the default LLMProvider implementation)
      embeddings/     Local sentence-transformers embedder (the default EmbeddingProvider)
      retrieval/      SearchProvider abstraction: search_provider.py (interface),
                      memory_search.py (dev/test), azure_search.py (production), hybrid_search.py
                      (thin dispatcher used by agents/routers)
      agents/         Meeting router, retrieval/answer/discussion/decision agents, prompts
      conversations/  ConversationProvider abstraction (Internal / Teams)
      realtime/       WebSocket connection manager
      security/       JWT, OAuth state (CSRF), token revocation, authorization checks, audit log
      api/routers/    FastAPI route handlers
      db/             SQLAlchemy models, session (SQLite/Azure SQL, dialect-agnostic)
    alembic/          Migrations (portable — no PostgreSQL-specific SQL)
    tests/            unit / integration / e2e
  frontend/
    src/app/          Next.js App Router pages (dashboard, meetings, groups, search, feedback, settings)
    src/components/   Chat message, share-to-group modal, nav, auth guard
    src/lib/          API client, auth context, shared TS types
```

No Docker is used — see `docs/DEPLOYMENT.md` for the local-process setup (SQLite by default,
Python venv, `npm run dev`/`npm run start`).

## Why this stack

- **FastAPI**: async-native, typed request/response schemas (Pydantic), native WebSocket
  support, mature SQLAlchemy/Alembic ecosystem.
- **SQLite (dev/test) / Azure SQL (production)**: the relational store holds only application/
  transactional data (users, tenants, conversations, groups, feedback, decisions, action items) —
  never vector embeddings or transcript chunks. `create_async_engine` is dialect-agnostic at the
  call site; nothing downstream depends on PostgreSQL-specific SQL any more.
- **SearchProvider abstraction (Azure AI Search in production, an honestly-labeled in-memory
  provider for dev/test)**: keyword, vector, hybrid, and semantic search over transcript chunks —
  replaces both PostgreSQL full-text search and the prior Python/numpy vector similarity. See
  `docs/RAG_ARCHITECTURE.md`.
- **LLMProvider/EmbeddingProvider abstraction**: Anthropic Claude + local sentence-transformers
  remain the default, working providers (no external Azure credentials required to run this app
  today); `AzureOpenAILLMProvider`/`AzureOpenAIEmbeddingProvider` are real, alternate
  implementations selected via `LLM_PROVIDER=azure_openai` / `EMBEDDING_PROVIDER=azure_openai`
  once Azure OpenAI credentials are provisioned — see `docs/AZURE_SETUP.md`.
- **Next.js + React + TypeScript + Tailwind**: per the brief's default frontend stack.

## Request flow: asking a question

1. Frontend calls `POST /api/chat` with `{meeting_id, conversation_id?, message}`.
2. `security/authz.get_authorized_meeting` verifies the caller's tenant + participant/organizer
   status before anything else runs (see `docs/SECURITY.md`).
3. `agents/meeting_router` decides retrieval scope (single meeting, unless the question is an
   explicit cross-meeting request) and extracts a speaker filter if the question names a
   participant.
4. `retrieval/hybrid_search` calls `get_embedding_provider().embed_query(...)`, then the active
   `SearchProvider`'s `hybrid_search(tenant_id=..., meeting_ids=..., ...)` — the mandatory
   `tenant_id` + `meeting_id` filters are enforced inside the provider itself, never optional.
5. `agents/answer_agent` builds a grounded prompt (`agents/prompts.py`) from the retrieved
   excerpts + conversation history and calls `get_llm_provider().complete(...)`. The model must
   cite excerpts as `[S1]`, `[S2]`, …; citations are mapped back to the exact chunk metadata
   (speaker/timestamp) — never trusted as free text.
6. The answer, `AIResponse`, and `AISource` rows are persisted; the response returns the answer,
   sources, and whether the evidence was sufficient.

## Historical Meeting Data Import

A second ingestion entry point alongside live Graph/manual transcript loading: a folder of mixed
Teams transcripts and supporting documents (Word, Excel, PDF, PowerPoint, text, CSV) is parsed,
chunked, embedded, and indexed through the *same* `SearchProvider`/RAG pipeline live transcripts
use — there is no separate historical RAG implementation. See `docs/HISTORICAL_IMPORT.md` for the
full pipeline, meeting-association rules, duplicate detection, and security model.

## Known architectural limitations

- WebSocket fan-out is in-process (`realtime/ws_manager.py`); a multi-instance deployment needs
  a shared pub/sub layer (e.g. Redis) — noted in `docs/DEPLOYMENT.md`.
- Microsoft Graph / Teams integration code paths are real but unexercised against a live tenant
  in this environment (no Azure AD app registration available) — see
  `docs/MICROSOFT_GRAPH_PERMISSIONS.md`.
- **Azure SQL, Azure AI Search, and Azure OpenAI have not been live-tested against real Azure
  resources in this environment** (none are available here). Each has a real implementation
  behind its abstraction, validated via unit tests with mocked HTTP/config, and is inert
  (raises a clear "not configured" error) rather than silently falling back to anything else when
  credentials aren't present — see `docs/AZURE_SETUP.md` and the final implementation report's
  stated limitations.
