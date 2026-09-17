# Pre-Upgrade Audit — Historical Meeting Data + Unified Document Intelligence

Written before any implementation change for this upgrade. Scope: the Meeting Copilot / Teams
Meeting Intelligence application at `app/backend` + `app/frontend`. Goal: establish what exists
today so the upgrade extends it rather than duplicating or replacing working functionality.

## 1. Existing architecture

FastAPI backend (`app/backend/src/meeting_intel/`) + Next.js/React frontend (`app/frontend/`).
No Docker. Already fully PostgreSQL-free as of the prior refactor (see
`docs/MIGRATION_FROM_POSTGRES.md`): SQLite (dev/test, `aiosqlite`) or Azure SQL
(`AZURE_SQL_CONNECTION_STRING`) for relational data; a `SearchProvider` abstraction
(`retrieval/search_provider.py`) with an in-memory dev/test implementation
(`retrieval/memory_search.py`) and a real Azure AI Search REST client
(`retrieval/azure_search.py`) for transcript search; a `LLMProvider`/`EmbeddingProvider`
abstraction (`providers.py`) with Anthropic/local-sentence-transformers as the working defaults
and Azure OpenAI as a real, inert-without-credentials alternate.

Module layout relevant to this upgrade:
```
src/meeting_intel/
  ingestion/        transcript_parser.py (VTT), chunker.py, pipeline.py (Graph + manual load)
  retrieval/        search_provider.py (interface), memory_search.py, azure_search.py, hybrid_search.py (dispatcher)
  providers.py       LLMProvider/EmbeddingProvider abstraction
  agents/            meeting_router, retrieval_agent, answer_agent, discussion_agent, decision_agent, prompts
  db/                models.py (SQLAlchemy), session.py
  api/routers/       auth.py, meetings.py, chat.py, groups.py, messages.py, discussions.py
  security/          authz.py, jwt.py, session_security.py
  graph/             client.py (Microsoft Graph)
  auth/              entra.py, dev.py, deps.py
  conversations/     provider.py (ConversationProvider: Internal/Teams)
```

## 2. Existing ingestion flow

Two paths converge on the same indexing logic (`ingestion/pipeline.py: _index_transcript_text`):

1. **Graph-backed** (`load_meeting_from_graph`): resolves a Teams Join Meeting ID via
   `graph/client.py`, fetches attendance + the VTT transcript. Inert (`503`) without a real Azure
   AD app registration — none is available in this environment.
2. **Manual upload** (`load_meeting_manual`): a documented fallback taking raw VTT text directly
   (`POST /api/meetings/load` with `transcript_vtt`), used by the frontend when Graph is
   unconfigured and by the test suite.

Both call `_index_transcript_text`, which: parses VTT (`transcript_parser.parse_vtt`) → chunks
same-speaker runs (`chunker.chunk_cues`, ~900 chars/chunk) → embeds via
`providers.get_embedding_provider()` → builds `retrieval.search_provider.IndexableChunk` objects
(one `SearchProvider`, keyed by `tenant_id`+`meeting_id`, no relational storage of chunk content)
→ `get_search_provider().index_chunks(...)`.

**Only VTT is supported today.** There is no file upload endpoint at all — `transcript_vtt` is a
plain string field in a JSON POST body, pasted by the user in a `<textarea>`
(`app/frontend/src/app/meetings/page.tsx`). No Word/Excel/PDF/PowerPoint/CSV/TXT/legacy-.doc
parsing exists anywhere in the codebase. This upgrade's parser architecture (§7 of the task spec)
is entirely new — there is no existing per-format ingestion logic to conflict with or duplicate.

## 3. Existing RAG flow

`agents/meeting_router.py` decides retrieval scope (single meeting by default; cross-meeting only
on an explicit phrase match) and extracts a speaker filter. `agents/retrieval_agent.py` resolves
`meeting_ids` and calls `retrieval/hybrid_search.py`, which embeds the query and calls
`get_search_provider().hybrid_search(tenant_id=..., meeting_ids=..., ...)` — the mandatory
tenant+meeting filter is enforced inside the provider. `agents/answer_agent.py` builds a grounded
prompt (`agents/prompts.py`), calls the LLM, and maps `[S1]`/`[S2]` citation markers back to the
*exact* retrieved `SearchHit` (never trusting the model to state a speaker/timestamp itself).

This RAG pipeline is storage-agnostic already — it consumes `SearchHit` objects, not SQL rows —
so extending it to also retrieve non-transcript document chunks is additive: new chunks need only
be indexed through the same `SearchProvider.index_chunks()` call with the right metadata: no
separate retrieval code path is needed. `SearchHit`/`IndexableChunk` currently model only
transcript-shaped metadata (`speaker_name`, `start_time`, `end_time`) and must be extended (not
replaced) with document-shaped fields (`source_file`, `page_number`, `sheet_name`, `slide_number`,
`section`, `file_type`, `document_type`) — see §23 of the task spec.

## 4. Existing database

SQLAlchemy 2.0 async ORM, SQLite (dev/test) / Azure SQL (production) — see
`docs/DATABASE.md`. Relevant existing tables: `meetings` (unique on `(tenant_id, ms_meeting_id)`
— this upgrade's deterministic `historical_<hash>` IDs slot directly into `ms_meeting_id`, no
schema change needed there), `meeting_participants`, `meeting_transcripts` (one row per meeting,
raw VTT text inline), `ai_sources` (citation metadata; currently transcript-shaped only:
`speaker`, `start_seconds`, `end_seconds` — needs new nullable columns for document citations),
`audit_log`, `oauth_states`, `revoked_tokens`. **There is no existing table for a generic
uploaded/imported file, an import job, or a non-transcript document** — these are new additions,
not overlaps with anything existing.

No PostgreSQL references exist anywhere in this database layer today (verified by the same
repo-wide scan used in the prior refactor — see §12 below).

## 5. Existing search implementation

`retrieval/search_provider.SearchProvider` (ABC): `index_chunks`, `delete_meeting`,
`chunks_for_meeting`, `keyword_search`, `vector_search`, `hybrid_search`. Two implementations:
`InMemorySearchProvider` (dev/test, honestly labeled, real RRF fusion) and
`AzureAISearchProvider` (real `httpx` REST client, inert without `AZURE_SEARCH_*` credentials,
raises `SearchNotConfiguredError` rather than fabricating results). The Azure index schema today
has exactly the transcript-chunk fields listed in `docs/RAG_ARCHITECTURE.md` (`id`, `tenant_id`,
`meeting_id`, `meeting_join_id`, `meeting_title`, `meeting_date`, `speaker_id`, `speaker_name`,
`start_time`, `end_time`, `content`, `content_type`, `chunk_index`, `source`, `document_id`,
`embedding`). This is the **one existing search engine** this upgrade must extend in place — the
task spec explicitly forbids creating a second one, and there is no reason to: adding fields to
this same schema and object model is sufficient.

## 6. Existing LLM/embedding provider

`providers.py`: `LLMProvider`/`EmbeddingProvider` Protocols. Working defaults: Anthropic Claude
(`llm/client.py`) + local `sentence-transformers` (`embeddings/embedder.py`, 384-dim). Real,
inert-without-credentials alternates: `AzureOpenAILLMProvider`/`AzureOpenAIEmbeddingProvider`.
Nothing here needs to change for document ingestion — the same `embed_texts()` call that embeds
transcript chunks today will embed document chunks; the interface is content-agnostic.

## 7. Existing Teams/Graph integration

`graph/client.py` (MSAL + `httpx`, real but inert without a live Azure AD app registration),
`auth/entra.py`, `conversations/provider.py` (`InternalChatProvider`/`TeamsChatProvider` — AI
agents never call Graph directly). Live transcript retrieval and historical file import are
independent entry points that must converge on the same ingestion/indexing code
(`ingestion/pipeline.py` today; this upgrade generalizes it to `ingestion/documents.py` +
parsers, with VTT handling refactored into a `VTTParser` that wraps the existing
`transcript_parser.parse_vtt`/`chunker.chunk_cues` rather than duplicating that logic).

## 8. Existing frontend functionality

Next.js App Router (`app/frontend/src/app/`): `dashboard`, `meetings` (list + "load meeting" form
with a manual-VTT-paste fallback), `meetings/[id]` (detail, chat, search, sources), `groups`,
`groups/[id]`, `feedback`, `search`, `settings`, `login`. `src/lib/api.ts` is a small JSON-only
`fetch` wrapper (no multipart/file upload support today — needed for historical import). No
folder/file upload UI exists anywhere in the frontend. `src/lib/types.ts` mirrors backend Pydantic
schemas 1:1; API response shapes are stable and versioned by convention, not by a formal schema
version — this upgrade must add fields additively (never rename/remove existing fields) to avoid
breaking the existing UI.

## 9. Existing tests

`app/backend/tests/`: 58 tests (`unit/`: transcript parser, chunker, meeting router,
prompts/grounding, in-memory search provider, Azure AI Search REST client against mocked HTTP;
`integration/`: meeting ingestion, authz, auth/session security; `e2e/`: one full acceptance-flow
test). All run against a real temporary SQLite database and the in-memory search provider — no
external service required. No frontend automated tests exist (`app/frontend/package.json` has no
test script) — a manual Playwright pass was run once during initial development, not in CI.

## 10. Known limitations (pre-existing, unrelated to this upgrade)

- Azure SQL, Azure AI Search, and Azure OpenAI have never been exercised against real Azure
  resources in this environment (none available) — only against SQLite/mocked HTTP/local models.
- WebSocket fan-out is in-process (no multi-instance support).
- No live Microsoft Graph/Entra ID tenant available to test against.
- No frontend automated test suite.

## 11. Current PostgreSQL references

Re-ran the same repo-wide case-insensitive scan used to close out the prior refactor
(`postgres|postgresql|pgvector|psycopg|psycopg2|asyncpg|CREATE EXTENSION|tsvector|to_tsvector|
plainto_tsquery|websearch_to_tsquery`) across `app/backend/src`, `app/backend/alembic`,
`app/backend/tests`, `app/backend/requirements.txt`, `.env.example`, and `app/frontend`:

**Zero runtime/executable matches.** The only hits repo-wide are prose comments/docstrings
explicitly describing the completed migration (e.g. "PostgreSQL-free refactor", pointers to
`docs/MIGRATION_FROM_POSTGRES.md`) and that document itself, which is explicitly labeled
historical. `pip freeze` in the backend venv has no `psycopg`/`psycopg2`/`asyncpg`/`pgvector`
packages installed. This is the correct starting state for this upgrade, and this upgrade
introduces no PostgreSQL dependency anywhere (new parser packages — `python-docx`, `openpyxl`,
`pypdf`, `python-pptx` — have no relation to any database).

## 12. Reusable components identified (do not duplicate)

| Need | Reuse | Do not create |
|---|---|---|
| VTT parsing | `ingestion/transcript_parser.parse_vtt` + `chunker.chunk_cues` | a second VTT parser |
| Chunk storage/retrieval | `retrieval/search_provider.SearchProvider` (both implementations) | a second search engine or vector store |
| Embeddings | `providers.get_embedding_provider()` | a new embedding call site |
| Tenant/meeting authorization | `security/authz.py` (`get_authorized_meeting`, `get_all_authorized_meeting_ids`) | new ad-hoc authorization checks |
| Meeting model | `db/models.Meeting` (keyed by `(tenant_id, ms_meeting_id)`) | a parallel "historical meeting" table |
| Citation display | `agents/prompts.format_excerpts`, `answer_agent._parse_citations`, `AISource` | a second citation mechanism |
| API client / auth | `src/lib/api.ts`, `src/lib/auth.tsx` | a separate fetch wrapper for import endpoints |
| Async DB session pattern | `db/session.get_db`, `AsyncSession` throughout | a synchronous side-channel for import jobs |

## Conclusion

The application is a solid, already-PostgreSQL-free foundation. This upgrade's job is purely
additive: a new parser layer feeding the *same* `SearchProvider`/RAG pipeline, new DB tables for
import jobs and document metadata (no changes to existing table semantics beyond additive
nullable columns on `ai_sources`), a new API surface for batch import, and new frontend
components — none of it requires removing or restructuring working code.
