# Testing

## What's covered

`app/backend/tests/`, run with `pytest` against a real, isolated, temporary SQLite database (via
the async `aiosqlite` driver) — no PostgreSQL, no external database server, no setup required.
**107 tests, all passing** as of this writing (`python -m pytest -q`, ~13-15s local wall time,
including one end-to-end test that loads a real sentence-transformers model).

### Unit (`tests/unit/`, no database)

- `test_transcript_parser.py` — WebVTT parsing: speaker extraction, timestamp conversion, cues
  without text, cues without a `<v>` tag.
- `test_chunker.py` — same-speaker merging, speaker-change chunk boundaries, max-length
  splitting, and a "no character is lost" invariant across chunking.
- `test_meeting_router.py` — default single-meeting scope, explicit cross-meeting phrase
  detection, speaker-filter extraction (including "What did Chetan say" → `Chetan Kumar`).
- `test_prompts_and_grounding.py` — excerpt formatting includes speaker+timestamp; the untrusted-
  data warning and tag wrap retrieved content; citation markers (`[S1]`) map back to the exact
  chunk; out-of-range citations fall back sanely; the insufficient-evidence message is exact and
  stable; decision-agent response parsing (conservative "no" case, action items with/without an
  owner).
- **`test_memory_search.py`** — the `InMemorySearchProvider`: keyword word-overlap scoring,
  vector cosine ranking, hybrid RRF fusion, chunk ordering, and — critically — **tenant and
  meeting isolation** (a query scoped to one tenant/meeting never returns another's chunks).
- **`test_azure_search.py`** — the `AzureAISearchProvider`, entirely against mocked HTTP (no live
  Azure resource): the provider raises `SearchNotConfiguredError` *before any HTTP call* when
  unconfigured; the index schema it would create (all 24 fields — the original 16 plus the
  historical-import citation fields, vector dimensions sourced from the active embedding
  provider's config, vector search + semantic search sections); document upload sends
  `mergeOrUpload` actions; every query includes a mandatory `tenant_id`+`meeting_id` OData filter;
  OData special characters (`'`) are escaped to prevent filter injection; a transport failure
  surfaces as `SearchNotConfiguredError`, never a fabricated result.
- **`test_parsers.py`** — every historical-import `DocumentParser` (VTT, text, Word, Excel, PDF,
  PowerPoint, CSV): a valid file, an empty file, a corrupted file, and — for legacy `.doc`/`.xls`
  and scanned/image PDFs — the "reported unsupported, never crashed or silently accepted" contract.
- **`test_file_safety.py`** — path traversal, absolute paths, null bytes, and filename
  sanitization for the historical import upload endpoint.
- **`test_meeting_association.py`** — the deterministic `historical_<hash>` id generator (the same
  folder produces the same id on a repeat import) and folder-based grouping.

### Integration (`tests/integration/`, real DB via httpx `ASGITransport`)

- `test_meeting_ingestion.py` — manual transcript upload indexes correctly (status, duration,
  participants); sources preserve speaker/timestamp; Graph-path returns `503` (not fabricated
  data) when unconfigured; re-loading the same Meeting ID is idempotent (regression test for a
  real bug found during manual QA).
- `test_authz.py` — no/invalid token rejected; cross-tenant meeting access returns `404`;
  same-tenant non-participant access returns `403`; a user cannot read another user's private
  conversation; a non-member cannot post to a group.
- **`test_auth_security.py`** — three security fixes made during the PostgreSQL-removal
  refactor: (1) the Entra OAuth `state` is now server-persisted, single-use, and validated on
  callback (rejected *before any MSAL/Graph call*), where it was previously accepted from the
  client and never checked; (2) `POST /api/auth/logout` immediately revokes the session token
  (checked via a `RevokedToken` table + the JWT's `jti` claim), and does not affect other users'
  tokens; (3) sharing a group-sourced AI message now requires membership in the *source* group,
  not only the destination group (previously any tenant user could re-share it).
- **`test_historical_import.py`** — the full Historical Meeting Data Import pipeline end to end
  via the real HTTP API: a mixed VTT+Word folder upload indexes into one meeting; an unsupported
  file and a corrupted file don't abort the rest of the batch; duplicate detection within one
  batch and across repeated imports of the same folder; cross-document retrieval (a search
  returns both a transcript chunk and a `.docx` chunk); tenant isolation between two tenants'
  imports and import history; and security cases (unauthenticated upload rejected, path traversal
  in a relative path rejected, an oversized file rejected, an empty upload rejected).

### End-to-end (`tests/e2e/test_full_flow.py`)

One test walking the full acceptance-criteria flow at the API level: login → load meeting (manual
transcript) → ask a question (verifies meeting isolation + speaker-filter extraction, against the
real `InMemorySearchProvider` and a real local embedding model) → follow-up question in the same
conversation → feedback → create group → share AI answer to group ("Discuss with Group") → group
message with `ask_ai` → decision suggestion → human-confirmed decision → action item with an
assigned owner.

**A true browser E2E (Playwright against the running Next.js UI) was run manually during initial
development** (not checked into the automated suite; not re-run for this refactor since no
frontend/API contract changed) — see `docs/DEPLOYMENT.md`.

## Running the suite

```bash
cd app/backend
source .venv/bin/activate
python -m pytest -q
```

`tests/conftest.py` creates a real, temporary SQLite database file per test session, runs
Alembic-equivalent schema creation against it, deletes all rows between tests for isolation
(`_clean_tables`, also resets the `InMemorySearchProvider`'s in-process store), and overrides the
FastAPI `get_db` dependency with a session bound to each test's own event loop.

## Security tests

Covered by `tests/integration/test_authz.py` (unauthorized meeting access, cross-tenant access,
non-participant same-tenant access, cross-user conversation access, non-member group posting) and
`tests/integration/test_auth_security.py` (OAuth CSRF state validation, session logout/
revocation, source-group membership on message sharing) — see above. Tenant/meeting isolation at
the search layer is additionally covered directly by `tests/unit/test_memory_search.py` and
`tests/unit/test_azure_search.py`'s mandatory-filter assertions. Prompt-injection separation is
covered structurally (see `docs/SECURITY.md`); a live-LLM adversarial run was not performed for
lack of a configured `ANTHROPIC_API_KEY`/Azure OpenAI credentials in this environment.

## Not covered / explicitly out of scope for this pass

- Load/concurrency testing of the WebSocket layer.
- A live Microsoft Graph integration test (no Azure AD app registration available).
- A live Anthropic or Azure OpenAI API call test (no usable credentials in this sandbox); the LLM
  call itself is a thin, standard SDK wrapper, and all logic around it (prompt construction,
  citation parsing, fallback behavior) is unit-tested independently of the network call.
- **A live Azure SQL Database or Azure AI Search integration test** — no Azure subscription is
  available in this environment. The `AzureAISearchProvider` is tested against mocked HTTP
  (request/response shape, schema, filter construction, unconfigured-error contract), which
  verifies the client's own logic but does not prove behavior against a real Azure Search
  service. Azure SQL is only exercised indirectly: the SQLAlchemy/Alembic layer is dialect-generic
  and was verified against SQLite; the `AZURE_SQL_CONNECTION_STRING` path itself has not been
  run. See `docs/AZURE_SETUP.md` and the final implementation report.
- **A live Azure Blob Storage upload, real `.doc`/`.xls` conversion, and OCR for scanned PDFs** —
  none are available/implemented in this environment; see `docs/HISTORICAL_IMPORT.md`
  "Remaining limitations".
- A frontend automated test for the folder-upload UI (`/meetings/import`) — verified by a
  production build + lint pass and by exercising the underlying API end to end
  (`test_historical_import.py`), not by a browser-driven UI test.
