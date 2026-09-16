# RAG Architecture

This is the platform's `docs/RAG.md` — retrieval-augmented generation over meeting transcripts.
**No PostgreSQL, no pgvector, anywhere in this pipeline** — see
`docs/MIGRATION_FROM_POSTGRES.md` for what changed.

## Ingestion

```
Meeting ID
   │
   ├─ Graph path: GraphClient.find_online_meeting → get_transcripts → get_transcript_content_vtt
   │  (requires a real Azure AD app registration — see docs/MICROSOFT_GRAPH_PERMISSIONS.md)
   │
   └─ Manual-upload path: POST /api/meetings/load with transcript_vtt
      (documented fallback for meetings whose transcript isn't reachable via Graph, and how
       this environment's tests/demo exercise the pipeline without live Graph credentials)
   │
   ▼
ingestion/transcript_parser.py  — parse WebVTT into (speaker, start, end, text) cues
   ▼
ingestion/chunker.py            — merge same-speaker consecutive cues up to ~900 chars;
                                   a speaker change always starts a new chunk
   ▼
providers.get_embedding_provider().embed_texts(...)  — local sentence-transformers
                                   (all-MiniLM-L6-v2, 384-dim) by default, or Azure OpenAI
                                   embeddings (`text-embedding-3-*`) once configured
   ▼
retrieval.search_provider.IndexableChunk   — id, tenant_id, meeting_id, meeting_join_id,
                                   meeting_title, meeting_date, speaker_id, speaker_name,
                                   start_time, end_time, content, content_type, chunk_index,
                                   source, document_id, embedding
   ▼
get_search_provider().index_chunks(...)    — InMemorySearchProvider (dev/test) or
                                   AzureAISearchProvider (production)
```

No metadata is ever dropped between steps — the chunker's output carries speaker + both
timestamps through to the `IndexableChunk`, which the search provider indexes alongside the
embedding.

## Storage: the `SearchProvider` abstraction

Transcript chunks and their embeddings are **not** stored in the relational database — they live
entirely behind `retrieval/search_provider.SearchProvider` (`index_chunks`, `delete_meeting`,
`chunks_for_meeting`, `keyword_search`, `vector_search`, `hybrid_search`). Business logic
(`agents/retrieval_agent.py`, `agents/discussion_agent.py`, `api/routers/meetings.py`) depends
only on this interface, never on a specific backend's SDK or SQL.

Two implementations:

- **`retrieval.memory_search.InMemorySearchProvider`** (`SEARCH_PROVIDER=memory`, the default) —
  a real, working, in-process implementation for local development and tests: a process-local
  dict keyed by `(tenant_id, meeting_id)`, real word-overlap keyword scoring, real numpy cosine
  vector scoring, and Reciprocal Rank Fusion for hybrid ranking. **This is explicitly NOT Azure AI
  Search and is never presented as such** — it exists because Azure AI Search requires an Azure
  subscription that isn't available to every contributor or CI run.
- **`retrieval.azure_search.AzureAISearchProvider`** (`SEARCH_PROVIDER=azure_search`) — the
  production implementation: a real Azure AI Search REST client (`httpx`, no new SDK dependency)
  that creates/updates an index with the schema below, and uses Azure's own native hybrid +
  semantic ranking (`queryType=semantic`, `vectorQueries`) rather than a local RRF fusion. It is
  **inert** without `AZURE_SEARCH_ENDPOINT`/`AZURE_SEARCH_API_KEY`/`AZURE_SEARCH_INDEX` — it
  raises `SearchNotConfiguredError` before making any HTTP call, never fabricates a result. See
  `docs/AZURE_SETUP.md`.

### Azure AI Search index schema

| Field | Type | Attributes |
|---|---|---|
| `id` | `Edm.String` | key, filterable |
| `tenant_id` | `Edm.String` | filterable |
| `meeting_id` | `Edm.String` | filterable |
| `meeting_join_id` | `Edm.String` | filterable |
| `meeting_title` | `Edm.String` | searchable, filterable, sortable |
| `meeting_date` | `Edm.String` | filterable, sortable |
| `speaker_id` | `Edm.String` | filterable |
| `speaker_name` | `Edm.String` | searchable, filterable |
| `start_time` / `end_time` | `Edm.Double` | filterable, sortable |
| `content` | `Edm.String` | searchable |
| `content_type` | `Edm.String` | filterable |
| `chunk_index` | `Edm.Int32` | filterable, sortable |
| `source` | `Edm.String` | filterable |
| `document_id` | `Edm.String` | filterable |
| `embedding` | `Collection(Edm.Single)` | searchable, vector profile `default-profile`, HNSW/cosine |

Vector `dimensions` are read from `settings.azure_openai_embedding_dimensions` (when
`EMBEDDING_PROVIDER=azure_openai`) or `settings.embedding_dim` (local model) — **never
hardcoded**, so the index always matches whichever embedding model is actually deployed. A
semantic configuration (`AZURE_SEARCH_SEMANTIC_CONFIG`, default `"default"`) prioritizes
`meeting_title` as title, `content` as content, `speaker_name` as a keyword field.

## Retrieval

`retrieval/hybrid_search.py` is a thin dispatcher:

1. Embeds the query via `get_embedding_provider().embed_query(query)`.
2. Calls `get_search_provider().hybrid_search(tenant_id=..., meeting_ids=..., query=..., vector=..., speaker=..., top_k=...)`.
3. Wraps each `SearchHit` in a `RetrievedChunk` (score, vector_rank, keyword_rank) for the agents.

**In-memory provider**: keyword search scores word overlap; vector search scores cosine
similarity (numpy, unit-normalized dot product); hybrid search fuses both rankings via
Reciprocal Rank Fusion (`score = Σ 1/(60+rank)` across whichever list(s) a chunk appears in) — a
standard, parameter-light way to combine two heterogeneous rankings.

**Azure AI Search provider**: a single query with `queryType=semantic` and a `vectorQueries`
clause — Azure's own hybrid + semantic ranking (BM25 + vector + a semantic re-ranker) replaces
the local RRF fusion; no client-side score combination is needed.

**Metadata filtering**: `tenant_id` and `meeting_ids` are mandatory, non-optional parameters on
every `SearchProvider` method — enforced inside the provider itself (a query with no
`meeting_ids` short-circuits to an empty result before any lookup/HTTP call), never left to the
caller's discipline alone. Optional `speaker` filtering is additive.

## Strict tenant and meeting isolation

`tenant_id` and `meeting_ids` are always the caller's already-authorized values (see
`security/authz.py`), derived server-side from the authenticated session — **never** trusted from
the request body or frontend directly. `meeting_ids` has no default; every call site must decide
it explicitly. In normal operation it is `[current_meeting.id]`. The **only** way it becomes
larger is `agents/meeting_router.is_cross_meeting_query()` matching an explicit pattern
("compare … meeting", "across meetings", "previous meeting(s)", "last week's meeting", "other
meetings", "earlier meeting(s)", "all meetings") — in which case it becomes every meeting id the
*calling user* is authorized for (`security/authz.get_all_authorized_meeting_ids`), never every
meeting in the system.

For the Azure AI Search provider, this is enforced with a server-built, OData-escaped `filter`
clause on every query (`tenant_id eq '...' and (meeting_id eq '...' or ...)`) — never a
post-filter applied to unscoped results. For the in-memory provider, chunks are stored keyed by
`(tenant_id, meeting_id)` and a query only ever reads from the requested keys.

Covered by `tests/unit/test_memory_search.py` (tenant/meeting isolation, keyword/vector/hybrid
scoring) and `tests/unit/test_azure_search.py` (mandatory filter construction, OData escaping,
unconfigured-provider behavior) — see `docs/TESTING.md`.

General world knowledge is never substituted for missing evidence: the system prompt
(`agents/prompts.py: MEETING_QA_SYSTEM_PROMPT`) explicitly forbids outside knowledge for factual
meeting questions, and the Answer Agent falls back to a fixed "I couldn't find enough evidence…"
message whenever retrieval returns nothing.

## Grounding & citations

The Answer Agent never lets the model choose citation content — it can only reference the
excerpts it was actually given, tagged `[S1]`, `[S2]`, etc. `answer_agent._parse_citations()`
maps those markers back to the *exact* `SearchHit` objects that were retrieved, so a citation's
speaker/timestamp/excerpt shown to the user is always sourced from the search index, not from
anything the model generated. If the model cites nothing but excerpts were used, the top excerpt
is shown anyway so the user can still see what evidence existed.

## Search endpoint (no LLM)

`GET /api/meetings/{id}/search?q=...` exposes the same hybrid search directly (no generation
step) — this is what powers the "Search" tab, distinct from the grounded Q&A chat flow.
