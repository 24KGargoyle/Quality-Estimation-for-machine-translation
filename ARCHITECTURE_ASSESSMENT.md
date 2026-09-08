# Architecture Assessment — Agentic Teams Meeting Intelligence Platform

## 1. Current Repository State (before this change)

The repository `24kgargoyle/quality-estimation-for-machine-translation` is a **machine-translation
quality-estimation (QE) research project**. It has no relationship to meetings, chat, or
Microsoft Teams. Its contents prior to this work:

| File | Purpose |
|---|---|
| `Challenge_2.ipynb` | Notebook exploring HTER-based QE modeling |
| `Challenge2_FullDetailed_Report.pdf` | Write-up of the QE challenge |
| `Dataset_Challenge_2.xlsx`, `qe_dataset_*.csv`, `qe_eval_predictions.csv` | QE datasets/predictions |
| `README_Challenge2.md` | Notes for the QE challenge |
| `build_qe_labels.py`, `train_qe_regression.py`, `translate_and_evaluate.py` | Standalone Python scripts for building HTER labels and training a regression QE model |

There is **no**:
- backend framework, API, or web server
- frontend/UI of any kind
- database or persistence layer
- authentication/authorization system
- vector database, search index, or RAG pipeline
- LLM/agent integration
- Microsoft Graph / Teams integration
- test suite, CI, or Docker/deployment configuration

**Conclusion: there is nothing to reuse from the existing code for this platform.** The QE
scripts and notebooks are left untouched — this build lives in a new, isolated `app/` directory
so the two unrelated projects can coexist in one repository without interference.

## 2. Target Architecture

A new full-stack application is added under `app/`:

```
app/
  backend/    FastAPI (Python) — API, auth, ingestion, retrieval, agents, WebSockets
  frontend/   Next.js + React + TypeScript + Tailwind — UI
```

**Why FastAPI for the backend:** async-native (needed for LLM streaming + WebSocket group
chat), first-class Pydantic schemas (typed API contracts, required by the spec), mature
SQLAlchemy/Alembic ecosystem, native WebSocket support, and it keeps the whole repo in Python
so the same virtualenv/tooling conventions apply across the QE scripts and the new platform.

**Database:** PostgreSQL with the `pgvector` extension. Rather than standing up a second piece
of infrastructure (a dedicated vector DB) purely for embeddings, `pgvector` lets one Postgres
instance serve both the relational schema (users, meetings, conversations, feedback, …) and the
`transcript_chunks.embedding` column used for semantic search, combined with Postgres full-text
search (`tsvector`) for keyword search — this is the hybrid retrieval layer.

**Embeddings:** a local `sentence-transformers` model (`all-MiniLM-L6-v2`) is used for
vectorization. This avoids a hard dependency on a paid embeddings API key while still being a
real model (not a fabricated/mocked vector).

**LLM:** the Anthropic Messages API (`anthropic` Python SDK), configured via `ANTHROPIC_API_KEY`.
All prompts separate system instructions / retrieved transcript content / user turns to defend
against prompt injection (see `docs/AGENT_ARCHITECTURE.md` and `docs/SECURITY.md`).

**Microsoft Graph / Entra ID:** implemented behind a `GraphClient` interface
(`app/backend/src/meeting_intel/graph/client.py`) using MSAL confidential-client flow and the
Graph SDK/HTTP calls for meeting lookup, `onlineMeetings`, and `callTranscripts`. **This
requires a real Azure AD app registration** (tenant ID, client ID, client secret) that only the
customer/tenant admin can provision — those are not available in this environment. Per the
explicit instruction not to fake Graph responses as a "final" implementation, the code path is
real (real MSAL token acquisition, real Graph HTTP calls) but is inert until real credentials
are supplied via environment variables; with no credentials configured, endpoints that need
Graph return a clear `503 graph_not_configured` error rather than fabricated data. This is
documented in `docs/MICROSOFT_GRAPH_PERMISSIONS.md` and `docs/DEPLOYMENT.md`.

**Auth (application-level):** Entra ID OIDC (authorization-code + PKCE) is the primary login
path. Because there is no real Azure AD tenant available to test against in this environment, a
`dev` auth provider (explicitly gated by `AUTH_PROVIDER=dev`, refused in `AUTH_PROVIDER=entra`)
is included so the full application can be exercised end-to-end locally without live Azure
credentials. Both issue the same internal session JWT and populate the same `users` row/tenant
context, so swapping to real Entra ID at deploy time requires no application-logic changes —
only configuration.

**Conversation abstraction:** `ConversationProvider` interface with `InternalChatProvider`
(DB + WebSocket) and `TeamsChatProvider` (Graph `chatMessages`/channel messages) implementations,
so group chat, "Discuss with Group", and agent participation are not coupled to Teams.

## 3. Risks

- Microsoft Graph transcript/recording APIs require specific licenses, admin consent, and the
  meeting to have transcription enabled — cannot be validated without a live tenant.
- Embedding a ~90MB sentence-transformers model increases backend image size/cold start; noted
  in deployment docs with an alternative (hosted embeddings API) as a swap-in.
- True concurrent WebSocket load and Graph rate limiting are not load-tested here.
- Decision/action-item extraction is inherently probabilistic; the design intentionally requires
  human confirmation rather than auto-committing extracted decisions.

## 4. Migration Requirements

None — this is additive. No existing QE files are modified, moved, or deleted.

## 5. Implementation Phases (as executed)

1. Foundation: repo layout, config, DB schema/migrations, auth (dev + Entra scaffold), API skeleton.
2. Teams meeting ingestion: Graph client abstraction, meeting lookup + authorization, transcript
   parsing, speaker/timestamp preservation, background indexing pipeline.
3. Meeting intelligence: hybrid retrieval (pgvector + tsvector + metadata filters), grounded
   answer agent, strict meeting isolation, citations.
4. Private chat: conversation persistence, streaming answers, follow-up context resolution.
5. Feedback: 👍/👎 + reason capture, feedback table, evaluation-dataset export script.
6. Group collaboration: groups, WebSocket real-time chat, "Discuss with Group" context sharing,
   AI participation in group threads.
7. Teams collaboration: `TeamsChatProvider` implementation + `teams_mappings` table (inert
   without real Graph credentials, as above).
8. Agentic capabilities: Meeting Router → Retrieval Agent → Answer Agent; Discussion Agent;
   Decision/Action-Item agent with human confirmation step.
9. Hardening: authz checks on every meeting/group access, audit log, structured logging,
   input/output validation, unit + integration tests, documentation set.

See `IMPLEMENTATION_REPORT.md` for what was actually completed, partially completed, and
deliberately left as a documented follow-up.
