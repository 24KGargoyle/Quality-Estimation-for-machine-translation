# Customer-scoped operational intelligence

The optional operational layer wraps `/api/chat`. Existing authentication,
meeting authorization, message persistence, response schemas and the general
RAG pipeline remain in place. It is disabled by default. Search, intelligence and
raw source browsing also require a resolved customer when enabled. These endpoints
accept an optional `customer_id` query parameter and return HTTP 409 when selection
is needed. Group discussions retain their existing meeting authorization contract.

## Enable and roll back

1. From `app/backend`, run `alembic upgrade head`. The nullable conversation
   customer column is required even when the feature is disabled.
2. Copy `config/operational.example.json` to `config/operational.json`. Set real
   tenant, meeting and user IDs. Do not commit customer data. Catalog access is
   tenant-scoped and requires a configured meeting or user association in addition
   to the existing meeting authorization. No public customer registration API is added.
3. Add reviewed customer records and document bindings as described below.
4. Set `OPERATIONAL_ENABLED=true` and `OPERATIONAL_CATALOG_PATH=config/operational.json`.
5. For Azure Search, update the index using the existing `ensure_index()` service
   and reindex documents to populate the filterable `customer_id` field. Reindex
   memory content as well. Untagged chunks are excluded from scoped retrieval.

Set `OPERATIONAL_ENABLED=false` to restore the original chat pipeline. Keep the
additive migration. No Azure resources are provisioned by this change.

## Customer resolution

The stored conversation customer wins, then the optional `customer_id` request
field, then an explicitly named account, then a unique meeting/user association.
An ambiguous or unavailable account produces a selection request without retrieval.
The existing chat UI can select by naming the account in the message. Start a new
conversation to switch accounts. Roles come from the catalog's `roles` mapping of
authenticated user ID to operational role, not the application's admin/member role.
Timezone is configured per customer and the date is derived at request time.

General questions use the existing retriever with tenant, authorized meeting and
customer filters applied before ranking. Prior unscoped conversation history is
excluded from the model context. The chat intelligence panel uses only scoped
evidence; its extra meeting-wide search and external web research are suppressed.

## Approved records

### Answering directly from uploads

Set `OPERATIONAL_UPLOADED_EVIDENCE_ENABLED=true` to use uploaded reference documents
for procedures, account facts and daily checklists when there are no approved
records on that route. Keep document/customer bindings explicit: a mixed upload
folder is not proof that every file belongs to the same customer.

Configure `uploaded_sources` on the customer, mapping `PROCEDURE`, `ACCOUNT_INFO`
and `DAILY_TASKS` to lists of imported document IDs (`hist:<first 16 hash characters>`).
The content stays in the existing imported documents and index; do not copy steps
or task text into the catalog. The corresponding `document_bindings` must assign
those source IDs to the same tenant/customer/meeting. This opt-in path treats them
as uploaded references, not as approved/current SOPs, and logs MEDIUM confidence.

Uploaded procedural references require matching subject terms and can span
multiple same-customer documents. Multiple references alone are not treated as a
conflict. The existing model generates a cited partial overview when a full SOP is
absent, preserves ownership restrictions, and must distinguish actual disagreements.
If generation abstains despite relevant text, a clearly labeled, cited excerpt
answer provides supported details without manufacturing a sequence of steps.
The approved-SOP route remains restricted to one current authoritative procedure.
Daily checklists use
explicit `Daily`, `Daily / As Needed`, or weekday section headings and preserve
source conditions verbatim. Weekly/monthly headings without a due date are not
claimed as due today. Unknown personal role/access is disclosed. Other schedule
formats continue to require structured schedule metadata. Spreadsheet aggregation
still uses deterministic structured queries, never embedding-derived counts.

The local backend must restart after `.env` changes (settings are cached). Existing
chat responses and their sidebar contents are historical and are not rewritten;
send a new question to test the new route. Memory restoration now reapplies
customer metadata to previously untagged imported chunks for the scoped request.

Records are curated deployment data. Importing a spreadsheet or document does not
automatically mark it approved. The catalog is validated on every operational
request. A missing or malformed catalog fails closed.

Each record has `id`, `tenant_id`, `customer_id`, `source_type`, `title`, `topic`,
`status`, `version`, `effective_date`, optional `expires_on`, `owner` and
`authority_level`. Only approved records with authority at least
`OPERATIONAL_MIN_AUTHORITY` (default 80) and an effective
date on or before today are eligible. Numeric dotted versions are supported.
Newest effective date/version wins; equal-ranked duplicates abstain. An expired
latest version does not revive an older one. An optional `document_id` links a
record to a selected imported document (`hist:<first 16 hash characters>`).

Example record shape (illustrative steps, replace with reviewed SOP text):

```json
{
  "id": "bp-change-order-v3",
  "tenant_id": "YOUR_TENANT_ID",
  "customer_id": "bp",
  "source_type": "approved_sop",
  "title": "BP Change Order SOP",
  "topic": "change_order",
  "aliases": ["create a change order"],
  "status": "approved",
  "version": "3.1",
  "effective_date": "2026-01-01",
  "authority_level": 100,
  "steps": ["Reviewed step one", "Reviewed step two"]
}
```

Procedures return the complete curated `steps` from one record, without LLM
synthesis. Account records use `customer_master` or `account_roster`, an exact
topic such as `account_manager`, and an `answer`. Topic aliases must be curated
narrowly; this lightweight classifier does not perform arbitrary semantic intent
understanding. Unknown operational requests abstain.

The optional customer `sme` field supplies a reviewed contact string. Without it,
fallback names only the customer's account SME or account manager.

## Structured datasets

Use `source_type: structured_files`, `topic: sow`, `aliases: ["SOWs"]`, and a
column mapping such as `{"expiry_date": "SOW Expiry Date"}`. Provide inline `rows`
or `file: datasets/bp-sows.csv` / `.xlsx` relative to the catalog directory, and an
optional Excel `sheet`. Paths cannot escape that directory. The default date
format is `%Y-%m-%d`; set `date_format` explicitly for other formats.

Each file must belong exclusively to the declared customer, or map `customer_id`
to its customer discriminator column. Mixed-customer rows are filtered before
computation. Missing columns and invalid dates abstain, rather than undercounting.
“How many SOWs expire in September?” is supported directly, with an optional year.
If matching months span multiple years and no year was supplied, it abstains.

For other questions, add exact approved query mappings in a record's `queries`:

```json
{
  "What is the total SOW value by team?": {
    "operation": "sum",
    "column": "amount",
    "group_by": "team",
    "sort_by": "value",
    "descending": true,
    "filters": []
  }
}
```

Logical columns must map to actual headers in `columns`. Operations are `count`,
`sum`, `average`, and `table` (with `select`). Filters support `eq`, `lt`, `le`, `gt`,
`ge`, `month`, `year` and explicit `text`, `number`, `date` types. Grouped results
and projected tables can be sorted. Arithmetic uses decimal values. Unsupported
wording abstains. There is no arbitrary SQL execution or live database adapter;
database exports can be represented as approved inline rows. Excel formulas must
have cached values, otherwise computation abstains. Files are read synchronously;
this initial adapter is intended for bounded operational rosters, not large analytics.

## Task schedules

Use `source_type: task_schedule`, one stable `topic` per task, an `answer` with the
complete reviewed instruction and optional `role`. `frequency` is `daily`,
`weekly` (with `weekday`, Monday=0), `monthly` (with `day`), or `date` (with
`on_date`). Version and validity rules apply to schedules too. Missing role context
with role-specific schedules abstains. Include URLs, recipients and deadlines only
inside reviewed task text. SOP records are never inferred into scheduled tasks.

## Existing RAG document tagging

Add explicit `document_bindings` entries:

```json
{"tenant_id": "TENANT", "meeting_id": "MEETING", "document_id": "DOCUMENT", "customer_id": "bp"}
```

Both existing search providers apply these bindings during indexing/restoration.
Conflicting bindings are rejected. Explicit ingestion-supplied `customer_id` is
also supported. Do not infer ownership from titles or embeddings. Customer changes
require reindexing; old Azure documents are not automatically migrated.

## Evaluation and observability

`tests/unit/test_operational.py` covers intent routing, context priority, tenant
and customer isolation, SOP precision/versions, missing evidence, account lookup,
structured counts, ambiguity, schedules, aggregates and Azure filters. Run the
full backend suite with `python -m pytest -q` using the repository environment.

`operational_query` logs contain request/customer IDs, intent, selected sources,
record IDs, authority/status, score (null for deterministic lookup), confidence,
structured-query use, answer/fallback flags, safe reason codes and latency in ms.
Document content, queries, row values and contacts are excluded. HIGH denotes
validated deterministic evidence, MEDIUM the existing scoped general RAG route,
and LOW an abstention. Live Azure integration requires deployment verification.
