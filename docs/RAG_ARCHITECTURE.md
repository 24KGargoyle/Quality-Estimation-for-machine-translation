# RAG Architecture

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
embeddings/embedder.py          — sentence-transformers (all-MiniLM-L6-v2, 384-dim), local
   ▼
transcript_chunks table          — meeting_id, speaker, start/end seconds, text, embedding,
                                   generated tsv column, all preserved together per chunk
```

No metadata is ever dropped between steps — `TranscriptChunkData` carries speaker + both
timestamps through chunking, and the DB row keeps them alongside the embedding.

## Retrieval

`retrieval/hybrid_search.py` combines:
- **Vector search**: cosine similarity computed in Python — candidate chunks for the given
  `meeting_ids`/`speaker` are loaded from Postgres (`embedding` stored as plain JSON), stacked
  into a numpy matrix, and scored against the query embedding with a single dot product (both
  are unit-normalized, so dot product == cosine similarity). Deliberately **not** the `pgvector`
  Postgres extension: it has no plain installer on Windows (needs compiling from source with
  MSVC), which would otherwise force Docker or WSL2 onto Windows contributors just to run this
  app. This trades a DB-side ANN index for a simpler dependency footprint — fine at
  meeting-transcript scale (a search scope is at most a few hundred chunks), not for a corpus of
  millions of chunks (see `docs/DEPLOYMENT.md` "Production notes").
- **Keyword search**: Postgres full-text (`tsv @@ plainto_tsquery(...)`, ranked by `ts_rank_cd`)
  — this part *is* still done in the database; it's a stock Postgres feature, no extension needed.
- **Fusion**: Reciprocal Rank Fusion (`score = Σ 1/(60+rank)` across whichever list(s) a chunk
  appears in) — a standard, parameter-light way to combine two heterogeneous rankings without
  needing to calibrate raw score scales against each other.
- **Metadata filtering**: `meeting_ids` (always required — see below) and optional `speaker`.

Reranking beyond RRF (e.g. a cross-encoder) was scoped out — see `IMPLEMENTATION_REPORT.md`
"Known limitations."

## Strict meeting isolation

`meeting_ids` is a required parameter with no default — every call site must decide it
explicitly. In normal operation it is `[current_meeting.id]`. The **only** way it becomes
larger is `agents/meeting_router.is_cross_meeting_query()` matching an explicit pattern
("compare … meeting", "across meetings", "previous meeting(s)", "last week's meeting", "other
meetings", "earlier meeting(s)", "all meetings") — in which case it becomes every meeting id the
*calling user* is authorized for (`security/authz.get_all_authorized_meeting_ids`), never every
meeting in the system. This is covered by
`tests/unit/test_meeting_router.py` and exercised end-to-end in `tests/e2e/test_full_flow.py`
(default single-meeting path) — a dedicated cross-meeting authorization test is a natural
follow-up (see `IMPLEMENTATION_REPORT.md`).

General world knowledge is never substituted for missing evidence: the system prompt
(`agents/prompts.py: MEETING_QA_SYSTEM_PROMPT`) explicitly forbids outside knowledge for factual
meeting questions, and the Answer Agent falls back to a fixed "I couldn't find enough evidence…"
message whenever retrieval returns nothing.

## Grounding & citations

The Answer Agent never lets the model choose citation content — it can only reference the
excerpts it was actually given, tagged `[S1]`, `[S2]`, etc. `answer_agent._parse_citations()`
maps those markers back to the *exact* `TranscriptChunk` objects that were retrieved, so a
citation's speaker/timestamp/excerpt shown to the user is always sourced from the database, not
from anything the model generated. If the model cites nothing but excerpts were used, the top
excerpt is shown anyway so the user can still see what evidence existed.

## Search endpoint (no LLM)

`GET /api/meetings/{id}/search?q=...` exposes the same hybrid search directly (no generation
step) — this is what powers the "Search" tab, distinct from the grounded Q&A chat flow.
