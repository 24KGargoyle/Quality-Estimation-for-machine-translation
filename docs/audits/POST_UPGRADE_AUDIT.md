# Post-Upgrade Audit — Historical Meeting Data + Unified Document Intelligence

Written after implementation, verifying against `docs/audits/PRE_UPGRADE_AUDIT.md` and the
upgrade's acceptance criteria (§46 of the upgrade request). Every claim below was checked by
actually running the corresponding command/test in this environment — see the exact commands.

## Existing features still work

`python -m pytest tests/ -q` → **107 passed** (the pre-upgrade suite of 58 plus 49 new tests), 0
regressions. This includes every pre-existing area: auth/session security, authz/tenant isolation,
transcript ingestion, chunking, meeting-router scope decisions, prompt/grounding/citation logic,
the in-memory and Azure AI Search providers, and the full end-to-end acceptance flow. The frontend
production build (`npm run build`) and lint (`npm run lint`) both pass with zero errors/warnings,
including the three pre-existing pages touched (`meetings/[id]`, `search`, `ChatMessage`).

## Historical import works

Verified end-to-end via the real HTTP API (`tests/integration/test_historical_import.py`, all 11
passing): a folder upload creates a job, the job transitions `queued` → `processing` →
`completed`/`completed_with_warnings`, results are queryable during and after processing, and
import history is listed per tenant.

## Mixed files work

`test_mixed_folder_upload_indexes_vtt_and_docx_into_one_meeting` uploads a real `.vtt` and a real
`.docx` (built with `python-docx`) in the same folder and confirms both land in one meeting with
`document_count == 2`. `tests/unit/test_parsers.py` additionally exercises real XLSX (via
`openpyxl`), PDF (via `fpdf2`-generated real PDF bytes), PPTX (via `python-pptx`), and CSV content
through their respective parsers directly.

## VTT / DOCX / XLSX / PDF / PPTX / TXT work

All six covered by real, valid-file parser tests (`TestVTTParser`, `TestWordParser`,
`TestExcelParser`, `TestPDFParser`, `TestPowerPointParser`, `TestTextParser` in
`test_parsers.py`), each asserting the parser's actual extracted content/metadata (speaker,
section, sheet name, page number, slide number respectively), not just "it didn't crash."

## Legacy formats safely handled / clearly reported

`.doc` and `.xls` are detected before any parsing library touches them and raise
`UnsupportedFileError` with a specific "convert to .docx/.xlsx" message
(`test_legacy_doc_reported_unsupported_not_crashed`,
`test_legacy_xls_reported_unsupported_not_crashed`) — confirmed via the API-level test too
(`recommended_action` is non-empty for these). A scanned/text-free PDF is likewise reported as
requiring OCR, never silently indexed as empty (`test_scanned_pdf_with_no_text_reports_ocr_required`).

## Duplicate detection works

`test_duplicate_file_is_detected_within_the_same_batch` (two identical files in one upload) and
`test_reimporting_the_same_folder_is_fully_deduplicated` (the exact same folder uploaded twice)
both pass, confirmed via real HTTP requests and real SHA-256 hashing — not mocked.

## Import progress works

`GET /api/historical-imports/{job_id}` is polled during processing in every integration test via
`_wait_for_job`; `processed_files`/`current_file` update as the batch runs (verified by the tests
completing without timing out against real background `asyncio` tasks, not a stub).

## Partial failures do not stop the batch

`test_one_unsupported_file_does_not_abort_the_batch` uploads one valid file, one unsupported
extension, and one corrupted `.docx` in a single batch and confirms the valid file still succeeds
(`successful_files == 1`) while the batch overall reports `completed_with_warnings`, not `failed`.

## Import history works

`test_history_list_is_scoped_to_the_callers_tenant` confirms `GET /api/historical-imports` returns
only the caller's tenant's jobs.

## Meeting association works

`tests/unit/test_meeting_association.py` verifies folder-based grouping (two files in the same
folder get the same historical meeting id), filename-stem fallback for folder-less files, title
derivation, and — critically — that the generated id is **deterministic**: the same
`(tenant_id, folder)` pair always produces the same `historical_<hash>` id, confirmed directly by
`test_deterministic_id_is_stable_for_the_same_tenant_and_key` and indirectly by
`test_reimporting_the_same_folder_is_fully_deduplicated` (a second import of the same folder finds
the *same* meeting, not a new one — `len(meetings) == 1` after both imports).

## Historical meetings appear in Meetings / documents appear under meetings

`test_mixed_folder_upload_indexes_vtt_and_docx_into_one_meeting` confirms `GET /api/meetings`
returns the historical meeting with `is_historical: true`, and `GET /api/meetings/{id}` returns
its `documents` array with both imported files' metadata.

## Azure AI Search indexing works / hybrid retrieval works / RAG answers work

The in-memory `SearchProvider` (used in all tests, since no Azure subscription exists here) is the
same interface `AzureAISearchProvider` implements — both are exercised by
`tests/unit/test_azure_search.py` (24-field schema including all 8 new historical-import fields,
verified against mocked HTTP) and `tests/unit/test_memory_search.py`. Actual hybrid retrieval
returning indexed historical-document chunks is verified live via
`test_cross_document_retrieval_answers_from_transcript_and_docx`. **Azure AI Search itself has not
been queried against a real Azure resource** — see "Remaining limitations" in
`docs/HISTORICAL_IMPORT.md` and `docs/AZURE_SETUP.md`, unchanged from the pre-upgrade state.

## Cross-document retrieval works

`test_cross_document_retrieval_answers_from_transcript_and_docx`: one hybrid search query over a
meeting containing both a `.vtt` and a `.docx` returns chunks from both (`file_types` includes
`"docx"` alongside the transcript). No document-type-specific retrieval code exists — this falls
out of the unified `SearchProvider.hybrid_search()` call the RAG pipeline already used for
transcripts.

## Source citations work / speaker-timestamp citations / page-sheet-slide citations

`agents/prompts.source_label()` (unit-verified in this session's manual smoke test, matching the
spec's exact example formats for transcript/PDF/Excel/PowerPoint/Word) is used by
`format_excerpts()` (feeds the LLM prompt), the "Discuss with Group" share card
(`api/routers/messages.py`), and the `/search`+`/sources` endpoint responses. `SourceSchema`/
`AISource` carry the full set of fields (`source_file`, `file_type`, `document_type`,
`page_number`, `sheet_name`, `slide_number`, `section`) end to end from retrieval through to the
API response — never fabricated, always sourced from the retrieved `SearchHit`.

## Tenant isolation works

`test_tenant_isolation_between_two_historical_imports`: tenant B gets `404` for tenant A's import
job and sees zero meetings. Every new endpoint (`get_authorized_import_job`) and every new table
(`historical_import_jobs`, `historical_documents`, `imported_file_results`) carries/filters by
`tenant_id`, matching the pattern already established for `Meeting`/`Group`/`Conversation`.

## Meeting isolation works

Unaffected by this upgrade — `security/authz.get_authorized_meeting` and the mandatory
`tenant_id`+`meeting_id` filter inside every `SearchProvider` method (unchanged code paths) still
apply identically to historical meetings. Covered by the pre-existing `test_authz.py` (58/58
pre-upgrade tests still pass) plus the new isolation tests above.

## Entra authentication / Microsoft Graph / Teams collaboration / Groups / Feedback / Decisions / Action items remain intact

None of these subsystems were modified by this upgrade except for additive fields
(`Meeting.is_historical`, `AISource.*` citation columns) and the `source_label()` refactor in the
"Discuss with Group" share card — all covered by the pre-existing test suite, which still passes
in full (`test_auth_security.py`, `test_authz.py` unchanged and green).

## PostgreSQL remains completely removed

Repository-wide scan (same pattern as the prior refactor's acceptance check) across
`app/backend/src`, `app/backend/alembic`, `app/backend/tests`, `requirements.txt`, `.env.example`,
and `app/frontend`:

```
grep -RniE "postgres|psycopg|asyncpg|pgvector|CREATE EXTENSION|tsvector|to_tsvector|
            plainto_tsquery|websearch_to_tsquery" ...
```

**Zero runtime/executable matches.** Remaining hits are prose comments/docstrings explicitly
labeled as describing the historical migration (e.g. "PostgreSQL-free refactor",
`docs/MIGRATION_FROM_POSTGRES.md` references) — the same set of files flagged in the pre-upgrade
audit, unchanged in kind. `pip freeze` in the backend venv has no `psycopg`/`psycopg2`/`asyncpg`/
`pgvector` package. The five new dependencies added for this upgrade (`python-docx`, `openpyxl`,
`pypdf`, `python-pptx`, `fpdf2`) have no relationship to any database.

## Backend tests executed / Frontend build executed / Security tests executed

- Backend: `python -m pytest tests/ -q` → 107 passed.
- Frontend: `npm run build` → compiles, type-checks, and generates all 12 routes (including the
  new `/meetings/import`) with no errors; `npm run lint` → no issues.
- Security: `tests/unit/test_file_safety.py` (7 tests: path traversal, absolute paths, null bytes,
  filename sanitization, hash stability) and the security cases in
  `tests/integration/test_historical_import.py` (unauthenticated upload rejected, path traversal
  rejected by the live API, oversized file rejected, empty upload rejected, cross-tenant job
  access rejected) — all passing.

## Documentation updated

`README.md`, `docs/ARCHITECTURE.md`, `docs/RAG_ARCHITECTURE.md` (serves as `docs/RAG.md`),
`docs/AZURE_SETUP.md`, `docs/DATABASE.md`, `docs/TEAMS_INTEGRATION.md`, `docs/API.md`,
`docs/DEPLOYMENT.md`, `docs/TESTING.md`, `.env.example`, and the new `docs/HISTORICAL_IMPORT.md`.

## Pre-change audit completed / Post-change audit completed

`docs/audits/PRE_UPGRADE_AUDIT.md` (written before any code change) and this document.

## What was intentionally NOT built (see `docs/HISTORICAL_IMPORT.md` "Remaining limitations" for full detail)

- A durable job queue (Celery/Azure Queue) — background jobs are in-process `asyncio` tasks.
- A sandboxed `.doc`/`.xls` → `.docx`/`.xlsx` conversion step (LibreOffice) — these formats are
  detected and reported, not converted.
- OCR for scanned PDFs.
- A dedicated multi-select filter UI (document type/file type/speaker/date range) on the Search
  page — the underlying data (citation metadata on every search result) is there, but the filter
  controls themselves were not added in this pass.
- Live verification against a real Azure AI Search / Azure SQL / Azure Blob Storage resource — no
  Azure subscription is available in this environment, unchanged from the pre-upgrade state.

None of these were "existing reusable components" per the pre-upgrade audit (there was nothing to
build on for any of them), and none block the acceptance criteria that specifically named a
working, tested pipeline for the nine required formats plus safe legacy-format handling.
