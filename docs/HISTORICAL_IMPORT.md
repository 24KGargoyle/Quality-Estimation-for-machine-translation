# Historical Meeting Data Import

Ingests a folder of historical meeting data — Teams transcripts (`.vtt`) plus supporting
documents (Word, Excel, PDF, PowerPoint, text, CSV) — into the same Meeting Copilot experience
that live Teams meetings use. Live Graph-sourced transcripts and historical files converge on the
same ingestion → chunk → embed → index pipeline (see `docs/RAG_ARCHITECTURE.md`); there is no
separate "historical" RAG implementation.

## Asking about one imported file

Open its meeting and choose the file in **Answer from**, then ask your question.
The selected file is validated against your tenant and meeting and filtered before
search ranking. Selecting a different file starts a fresh chat. Word citations show
the filename and section instead of inventing speaker names or timestamps.

With local file storage and `SEARCH_PROVIDER=memory`, the first question or search
after a backend restart rebuilds missing import chunks from the saved source files.
This can make the first request slower. Keep the local blob storage directory:
database document records alone cannot recreate the source text. This recovery
applies to historical imports; Azure AI Search maintains its own index.

## Supported formats

| Extension | Parser | document_type |
|---|---|---|
| `.vtt` | `VTTParser` (wraps the existing `transcript_parser`/`chunker`) | `transcript` |
| `.txt` | `TextParser` | `supporting_document` |
| `.docx` | `WordParser` | `transcript` when detected; otherwise `supporting_document` |
| `.doc` | `WordParser` | reported **unsupported** — see below |
| `.xlsx` | `ExcelParser` | `spreadsheet` |
| `.xls` | `ExcelParser` | reported **unsupported** — see below |
| `.pdf` | `PDFParser` | `reference_document` |
| `.pptx` | `PowerPointParser` | `presentation` |
| `.csv` | `CSVParser` | `spreadsheet` |

Anything else is reported as `unsupported` in the import results — never silently dropped.

### Legacy `.doc` / `.xls`

python-docx/openpyxl cannot read the pre-2007 OLE binary Word/Excel formats at all — attempting
to would either crash or silently misparse. These are detected up front and reported with a clear
"skipped, convert to .docx/.xlsx and re-upload" result, never claimed as successfully parsed. A
sandboxed `soffice --headless --convert-to docx` (LibreOffice) conversion step is the documented
production path for accepting `.doc`/`.xls` directly — **not implemented here**, since no such
sandboxed converter is available in this environment to safely build and verify.

### Scanned/image PDFs

A PDF with no extractable text layer (a scanned document) is reported as requiring OCR, never
indexed as an empty/successful document. OCR itself is not configured in this environment — see
"Remaining limitations" below.

## Uploading a folder

The frontend (`/meetings/import`) uses a browser folder picker:

```html
<input type="file" webkitdirectory directory multiple />
```

Each selected `File`'s `webkitRelativePath` (e.g. `Historical_Meetings/Project_A/Meeting_01.vtt`)
is sent to the backend as that file's multipart *filename* field
(`formData.append("files", file, file.webkitRelativePath || file.name)`) — `POST
/api/historical-imports` recovers both the plain filename and the full folder-relative path from
that one field, sanitizing both (see "Security" below) before anything else happens.

## API

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/historical-imports` | POST | Upload a batch of files (multipart), returns `{id, status: "queued", ...}` immediately |
| `/api/historical-imports/{job_id}` | GET | Poll job progress (`total_files`, `processed_files`, `successful_files`, `skipped_files`, `failed_files`, `current_file`, `status`) |
| `/api/historical-imports/{job_id}/results` | GET | Per-file outcome once the job is done (or partially done) |
| `/api/historical-imports` | GET | Import history for the caller's tenant, newest first |

Job `status` values: `queued`, `processing`, `completed`, `completed_with_warnings`, `failed`.
`failed` is reserved for a batch where nothing succeeded due to real errors — re-importing an
already-imported folder (100% duplicates, zero errors) is `completed_with_warnings`, not `failed`,
since recognizing duplicates correctly is the pipeline working as intended, not a failure.

A batch runs as a background `asyncio` task inside the same backend process — **there is no
separate worker/queue process** (no Celery/Redis available in this environment). This means an
in-flight import is lost if the backend process restarts mid-batch. For a production deployment
processing very large folders, replace `ingestion/historical_import.run_import_job`'s
`asyncio.create_task` call site with a real task queue (Celery, Azure Queue Storage + a worker,
etc.) — the function itself doesn't need to change, only how it's invoked.

## Pipeline (per file)

```
StagedFile (bytes + sanitized filename/relative_path, already size-checked)
   │
   ▼
file_hash = sha256(content)  — duplicate identity, independent of filename/path
   │
   ├─ already imported for this tenant? → recorded as "duplicate", chunks left as-is
   │
   ▼
ParserFactory.get_parser(file_type) → NormalizedDocument list (or UnsupportedFileError → "skipped")
   │
   ▼
resolve_meeting()  — associate with a real or historical meeting (see below)
   │
   ▼
get_embedding_provider().embed_texts(...)  — same embedding call live transcripts use
   │
   ▼
IndexableChunk list (source_file/relative_path/file_type/document_type/page_number/
sheet_name/slide_number/section carried through) → get_search_provider().index_chunks(...)
   │
   ▼
raw bytes → get_blob_storage().save(...)  (local disk by default, Azure Blob in production)
   │
   ▼
HistoricalDocument row (metadata only — never the file bytes) + ImportedFileResult row
```

One file's failure never aborts the batch: each file is processed independently (its own DB
session, bounded concurrency via `IMPORT_MAX_CONCURRENCY`, default 4) and gets its own outcome
row. A per-tenant `asyncio.Lock` serializes only the "find-or-create the meeting" step (to avoid
two files in the same new folder racing to insert the same meeting row) — parsing, embedding, and
indexing remain concurrent.

## Meeting association

1. **Explicit meeting ID** (when the caller supplies one) — preserved as-is; this is a real
   meeting, only its *documents* came from historical import.
2. **Exact title match** against an existing meeting in the same tenant (case-insensitive, never
   fuzzy — "do not make weak guesses").
3. Otherwise, a **new historical meeting** is created: files are grouped by their immediate parent
   folder (everything in `Project_A/` becomes one meeting); a file with no folder groups by its
   own filename stem. Its id is `historical_<sha256(tenant_id + grouping_key)[:16]>` — the same
   folder/file always produces the same id on a repeat import, never a random one. The title is
   derived from the folder/file name (underscores/dashes → spaces, title-cased); an embedded date
   (`2026-01-15`, `2026_01_15`) is appended to the title when present.

A meeting created this way has `is_historical=true` and appears in `/api/meetings` exactly like a
live Teams meeting — same schema, same chat/search/decisions/action-items/feedback endpoints.

## Duplicate detection

Identity is `(tenant_id, file_hash)` — a `UNIQUE` constraint on `historical_documents`. Uploading
the same file content again (even under a different name or path) is detected and recorded as
`duplicate`, never re-indexed or re-stored. A race between two files with identical content in one
batch (or two concurrent batches) is handled by catching the resulting `IntegrityError` and
recording the loser as a duplicate of the winner — not surfaced as a failure.

## Citations

Every retrieved chunk carries enough metadata to cite its exact source, never fabricated by the
LLM (see `docs/RAG_ARCHITECTURE.md` "Grounding & citations"):

| Source | Citation |
|---|---|
| Transcript | `Speaker: Alice · Timestamp: 00:08 · Source: Meeting transcript` |
| Word | `File: Architecture.docx · Section: API Architecture` |
| Excel | `File: Action_Items.xlsx · Sheet: Action Items` |
| PDF | `File: Design.pdf · Page: 7` |
| PowerPoint | `File: Architecture.pptx · Slide: 9` |

A single answer can cite multiple sources of different types in the same response (e.g. a
transcript excerpt *and* an Excel row) — retrieval isn't scoped to one document type, so a
question like "what did the team agree on and what's the action-item status?" can pull from both
the meeting transcript and `Action_Items.xlsx` in one hybrid search call.

## Security

- **Path traversal**: `security/file_safety.sanitize_relative_path`/`sanitize_filename` reject
  `..` segments, absolute paths, null bytes, and strip characters that are unsafe in a filesystem
  path — before the path is used for anything (blob storage key, database row, log line).
- **Oversized files**: a 50 MB per-file limit and a 2 GB per-batch limit
  (`security/file_safety.MAX_FILE_SIZE_BYTES`/`MAX_TOTAL_IMPORT_BYTES`), plus a 2000-file-per-batch
  cap — all enforced before any parsing happens.
- **No macro execution**: `openpyxl`/`python-docx`/`python-pptx` never execute VBA/macros — a
  `.xlsm`'s VBA project (if one were accepted) is inert binary data to these libraries, never run.
- **Tenant isolation**: `tenant_id` always comes from the authenticated session
  (`RequestContext.tenant_id`), never from the request body; every `HistoricalDocument`/`Meeting`/
  `HistoricalImportJob` row and every indexed chunk carries it, and every read endpoint filters by
  it (`security/authz.get_authorized_import_job`, tenant-scoped `Meeting` queries).
- **No local filesystem paths exposed**: API responses return only sanitized relative paths and
  opaque ids — never the on-disk blob storage path.
- **Sensitive content in logs**: `historical_import.py` logs file names and job/error metadata on
  failure, never full document content.

Covered by `tests/unit/test_file_safety.py` (path traversal, absolute paths, null bytes) and
`tests/integration/test_historical_import.py` (unauthenticated import rejected, path traversal
rejected by the API, oversized file rejected, cross-tenant job access returns 404).

## File storage

Raw uploaded files are stored via the `BlobStorage` abstraction (`storage/blob_storage.py`) —
`LocalBlobStorage` (default, real on-disk store under `FILE_STORAGE_DIR`, **not** Azure Blob
Storage) or `AzureBlobStorage` (`FILE_STORAGE=azure_blob`, a real Blob Storage REST client
authenticated via a container SAS URL, inert without `AZURE_STORAGE_CONTAINER_SAS_URL`). Only
metadata (hash, type, tenant, meeting, import job, blob reference) is stored in Azure SQL/SQLite —
never the file bytes themselves. See `docs/AZURE_SETUP.md`.

## Environment variables

```
FILE_STORAGE=local                          # or "azure_blob"
LOCAL_BLOB_STORAGE_DIR=./data/historical_blobs
AZURE_STORAGE_CONTAINER_SAS_URL=             # required when FILE_STORAGE=azure_blob
IMPORT_MAX_CONCURRENCY=4
```

## Testing

- `tests/unit/test_parsers.py` — every parser, valid/empty/corrupted/legacy-unsupported files.
- `tests/unit/test_file_safety.py` — path traversal, filename sanitization, hashing.
- `tests/unit/test_meeting_association.py` — deterministic id generation, folder grouping.
- `tests/integration/test_historical_import.py` — the full pipeline end to end via the real HTTP
  API: mixed-folder upload, partial failures not aborting the batch, duplicate detection (within
  and across jobs), meeting association, cross-document retrieval, tenant isolation, and the
  security cases above.

**Not verified**: a real Azure Blob Storage upload (no Azure subscription in this environment —
`AzureBlobStorage` is real client code, unverified against a live Azure resource); a real
LibreOffice `.doc`/`.xls` conversion step (not implemented); OCR for scanned PDFs (not
implemented); true multi-process/multi-worker concurrency (only in-process `asyncio` concurrency
with per-file DB sessions was exercised); import of a genuinely large folder (thousands of files)
for performance under load.

## Remaining limitations

- No durable job queue — an in-flight import is lost on a process restart (see "API" above).
- `.doc`/`.xls` are detected and reported, not converted.
- No OCR for scanned PDFs.
- Meeting-title matching is exact, case-insensitive — no fuzzy/similarity matching, by design
  (the spec explicitly says "do not make weak guesses").
- The search UI's advanced filters (by document type, file type, speaker, date range) described in
  the upgrade spec's "Search Experience" section are only partially built: the `/search` endpoint
  now returns the new citation metadata (file type, page/sheet/slide/section) that a filter UI
  would need, and results already span every ingested document type in one query, but a dedicated
  filter-by-type/date control was not added to the Search page in this pass.
