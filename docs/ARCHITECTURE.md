# Architecture

See `ARCHITECTURE_ASSESSMENT.md` at the repo root for the pre-implementation assessment
(what existed, what was reused, why this stack). This document describes the system as built.

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
   │ Microsoft     │◄────┤  Graph client            │      │ Anthropic Claude   │
   │ Graph API     │      │  Ingestion pipeline      │─────►│ (Messages API)     │
   └──────────────┘      │  Hybrid retrieval         │      └───────────────────┘
                         │  Agents (router/answer/   │
                         │   discussion/decision)    │
                         │  Conversation providers   │
                         │  WebSocket manager        │
                         └────────────┬─────────────┘
                                      │
                         ┌────────────▼─────────────┐
                         │ PostgreSQL (plain)        │
                         │ (relational + full-text;  │
                         │  vector similarity done   │
                         │  in Python, not the DB)   │
                         └───────────────────────────┘
```

## Directory layout

```
app/
  backend/
    src/meeting_intel/
      auth/          Entra ID (MSAL) + dev auth providers, session deps
      graph/          Microsoft Graph client (meetings, transcripts, chat messages)
      ingestion/      VTT transcript parsing, chunking, indexing pipeline
      embeddings/     Local sentence-transformers embedder
      retrieval/      Hybrid (vector + keyword) search
      agents/         Meeting router, retrieval/answer/discussion/decision agents, prompts
      llm/            Anthropic client wrapper
      conversations/  ConversationProvider abstraction (Internal / Teams)
      realtime/       WebSocket connection manager
      security/       JWT, authorization checks, audit log
      api/routers/    FastAPI route handlers
      db/             SQLAlchemy models, session
    alembic/          Migrations
    tests/            unit / integration / e2e
  frontend/
    src/app/          Next.js App Router pages (dashboard, meetings, groups, search, feedback, settings)
    src/components/   Chat message, share-to-group modal, nav, auth guard
    src/lib/          API client, auth context, shared TS types
```

No Docker is used — see `docs/DEPLOYMENT.md` for the local-process setup (Postgres install,
Python venv, `npm run dev`/`npm run start`).

## Why this stack

- **FastAPI**: async-native, typed request/response schemas (Pydantic), native WebSocket
  support, mature SQLAlchemy/Alembic ecosystem.
- **Plain PostgreSQL**: one database serves the relational schema *and* keyword search (via
  native `tsvector`/GIN). Vector similarity is computed in Python (numpy) rather than via the
  `pgvector` extension, which has no plain installer on Windows and would otherwise force
  Docker/WSL2 there — see `docs/RAG_ARCHITECTURE.md`.
- **sentence-transformers (local)**: real embeddings without a mandatory paid API key.
- **Anthropic Claude**: the LLM used for grounded answers, discussion assistance, and
  decision/action-item extraction, via the official `anthropic` SDK.
- **Next.js + React + TypeScript + Tailwind**: per the brief's default frontend stack.

## Request flow: asking a question

1. Frontend calls `POST /api/chat` with `{meeting_id, conversation_id?, message}`.
2. `security/authz.get_authorized_meeting` verifies the caller's tenant + participant/organizer
   status before anything else runs (see `docs/SECURITY.md`).
3. `agents/meeting_router` decides retrieval scope (single meeting, unless the question is an
   explicit cross-meeting request) and extracts a speaker filter if the question names a
   participant.
4. `retrieval/hybrid_search` runs vector (numpy cosine similarity, computed in Python) +
   keyword (Postgres full-text) search over `transcript_chunks`, fused via reciprocal rank
   fusion, filtered by meeting id(s) and speaker.
5. `agents/answer_agent` builds a grounded prompt (`agents/prompts.py`) from the retrieved
   excerpts + conversation history and calls the LLM. The model must cite excerpts as `[S1]`,
   `[S2]`, …; citations are mapped back to the exact chunk metadata (speaker/timestamp) — never
   trusted as free text.
6. The answer, `AIResponse`, and `AISource` rows are persisted; the response returns the answer,
   sources, and whether the evidence was sufficient.

## Known architectural limitations

- WebSocket fan-out is in-process (`realtime/ws_manager.py`); a multi-instance deployment needs
  a shared pub/sub layer (e.g. Redis) — noted in `docs/DEPLOYMENT.md`.
- Microsoft Graph / Teams integration code paths are real but unexercised against a live tenant
  in this environment (no Azure AD app registration available) — see
  `docs/MICROSOFT_GRAPH_PERMISSIONS.md`.
- Vector similarity is computed in Python rather than a DB-side ANN index, which is fine at
  meeting-transcript scale but wouldn't scale to millions of chunks — see `docs/RAG_ARCHITECTURE.md`.
