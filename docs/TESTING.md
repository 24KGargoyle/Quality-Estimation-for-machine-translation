# Testing

## What's covered

`app/backend/tests/`, run with `pytest` against a real Postgres + pgvector database (not
mocked/sqlite — the schema depends on pgvector and native full-text search, which sqlite can't
provide). 30 tests, all passing as of this writing.

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

### Integration (`tests/integration/`, real DB via httpx `ASGITransport`)

- `test_meeting_ingestion.py` — manual transcript upload indexes correctly (status, duration,
  participants); sources preserve speaker/timestamp; Graph-path returns `503` (not fabricated
  data) when unconfigured; **re-loading the same Meeting ID is idempotent** (regression test for
  a real bug found during manual QA — see below).
- `test_authz.py` — no/invalid token rejected; cross-tenant meeting access returns `404`;
  same-tenant non-participant access returns `403`; a user cannot read another user's private
  conversation; a non-member cannot post to a group.

### End-to-end (`tests/e2e/test_full_flow.py`)

One test walking the full acceptance-criteria flow at the API level: login → load meeting (manual
transcript) → ask a question (verifies meeting isolation + speaker-filter extraction) → follow-up
question in the same conversation → feedback → create group → share AI answer to group ("Discuss
with Group") → group message with `ask_ai` → decision suggestion → human-confirmed decision → 
action item with an assigned owner.

**A true browser E2E (Playwright against the running Next.js UI) was run manually during
development** (not checked into the automated suite) — it drove the exact same flow through the
real UI: dev login → load meeting via manual transcript paste → ask a question → 👎 feedback with
a reason → Discuss with Group → real-time WebSocket delivery of the shared context card into the
group chat → `ask_ai` group reply delivered live → decision-check. This caught one real bug (see
below) that the API-level tests alone had not — a good argument for adding it to CI as a
Playwright test in a follow-up, rather than leaving it manual.

### Bug found and fixed during this testing pass

Re-submitting the same Meeting ID (e.g. a page refresh, or a user double-clicking "Load
meeting") crashed with a Postgres unique-constraint violation, because `_index_transcript_text`
unconditionally created a new `meeting_transcripts` row even when one already existed. Fixed in
`ingestion/pipeline.py` to be a no-op when the meeting is already `ready`, and locked in by
`test_reloading_same_meeting_id_is_idempotent`.

## Running the suite

```bash
cd app/backend
sudo -u postgres psql -c "CREATE DATABASE meeting_intel_test OWNER meeting_intel;"
sudo -u postgres psql -d meeting_intel_test -c "CREATE EXTENSION IF NOT EXISTS vector;"
source .venv/bin/activate
python -m pytest -q
```

`tests/conftest.py` runs Alembic migrations once per session against `meeting_intel_test`,
truncates all tables between tests for isolation, and overrides the FastAPI `get_db` dependency
with an engine bound to each test's own event loop (avoids asyncpg cross-event-loop errors under
`pytest-asyncio`).

## Security tests

Covered by `tests/integration/test_authz.py` (see above): unauthorized meeting access,
cross-tenant access, non-participant same-tenant access, cross-user conversation access,
non-member group posting. Prompt-injection separation is covered structurally (see
`docs/SECURITY.md`); a live-LLM adversarial run was not performed for lack of a configured
`ANTHROPIC_API_KEY` in this environment. Cross-meeting retrieval's authorization boundary
(`get_all_authorized_meeting_ids`) is covered by unit tests on the router logic but not yet by an
integration test that actually attempts to retrieve from an unauthorized meeting via the
cross-meeting path — flagged as a follow-up in `IMPLEMENTATION_REPORT.md`.

## Not covered / explicitly out of scope for this pass

- Load/concurrency testing of the WebSocket layer.
- A live Microsoft Graph integration test (no Azure AD app registration available).
- A live Anthropic API call test (no usable API key in this sandbox — see
  `IMPLEMENTATION_REPORT.md`); the LLM call itself is a thin, standard SDK wrapper
  (`llm/client.py`), and all logic around it (prompt construction, citation parsing, fallback
  behavior) is unit-tested independently of the network call.
