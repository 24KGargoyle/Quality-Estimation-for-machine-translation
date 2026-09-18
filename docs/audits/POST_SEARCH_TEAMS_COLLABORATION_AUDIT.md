# Post Search / Teams Collaboration Audit

Date: 2026-09-18

## Scope

Incremental upgrade of the existing Meeting Copilot using the supplied sample as reference. Existing imports, document selection, internal groups and membership, feedback, collapsed references and Azure architecture are preserved. No PostgreSQL or pgvector dependency was added. The legacy search migration remains as a no-op revision so existing migration history stays valid; the new encrypted-token table follows the merged migration head.

## Implemented and checked

| Requirement | Implementation / verification |
| --- | --- |
| Query understanding and person intent | Known-name detection, ambiguity-safe speaker selection, document/topic/person intent; unit and search integration tests |
| Filtered hybrid retrieval and reranking | Tenant/authorized meeting/document filters retained, over-fetch then deterministic speaker/keyword reranking; Azure semantic ranking retained |
| Bounded grounded generation | At most 8 excerpts, 3,000 characters each, 18,000 evidence characters total; no full-transcript prompt |
| Structured result | Chat returns answer + evidence + sources + intelligence; citations retain real metadata, non-VTT timestamps are null |
| Evidence UI | Answer first, collapsed references, document selector retained; related sidebar collapsible |
| Contextual related items | Topics from evidence, documents with overlapping evidence terms, people supported by evidence or speaker metadata; unrelated roster names excluded |
| Optional external research | Explicit external request required, person/recap questions excluded; separate web results via Azure Responses; mocked citation and unsafe URL test |
| Actual participant resolution | Graph attendance identity IDs only, same configured Entra tenant; no guessed names/emails, historical and incomplete identities unresolved |
| Existing chat matching | Full paginated chat/member reads; exact ID sets, deterministic ordering, unknown/extra members excluded |
| Confirmed group creation | Required confirmed=true; participants checked against attendance; caller included; no automatic message send |
| Confirmed sending | Separate confirmation; saved answer authorized through private conversation; source excerpts server-loaded and HTML escaped; caller, recipient set and meeting identities rechecked |
| Graceful unavailability | Missing config/token returns explicit unavailable; Graph errors return 503, never simulated success; internal groups remain independent |
| Token/tenant security | Fernet encrypted tokens; configured tenant checks on login/token use; tenant-qualified mappings; conversation/meeting consistency enforced |

## Actual validation

- Backend: `python -m pytest tests/ -q --disable-warnings --tb=short`: **158 passed**, 8,802 warnings, 77.96 seconds. Includes existing unit, integration and API end-to-end regressions. SQLite migrations execute against a fresh temporary database. Warnings remain and are not counted as errors.
- Focused search/related/Teams run before final suite: **29 passed**.
- Network-guard verification: **10 passed**, including an explicit blocked socket test.
- Targeted ESLint on changed chat/search/sidebar/Teams components: passed.
- Frontend production build (`next build`), including TypeScript and all 12 static pages: **passed**. Initial sandbox build could not download existing Google fonts; expanded-access build succeeded after fixing a nullable filename type error.
- `git diff --check`: passed.

The first suite attempt was blocked by Windows sandbox temporary-directory access. An early expanded-access run inherited local Azure settings and attempted an Azure OpenAI call using test content; it failed with a provider content-filter response. Subsequent tests explicitly override live providers, run Hugging Face/Transformers offline and block external sockets and async connection creation. Automatic approval review rejected an intervening rerun until this isolation was established. The final passing suite made no live service calls.

## Limits and deployment checks

These tests use real FastAPI requests, SQLite and the local search/embedding implementation, with mocked external HTTP. They do not prove Azure SQL migration execution, Azure Search production index behavior, Azure OpenAI grounding quality, web-search deployment availability, Graph consent/application access policy, actual attendance record completeness or Teams delivery in the target tenant. No live Teams group was created or message sent during validation. No browser automation was run in this pass.

Query understanding and reranking are deterministic heuristics, not a trained entity resolver or cross-encoder. Related document matching is lexical evidence overlap. The raw Search page remains retrieval-only for compatibility; the meeting Q&A endpoint provides the unified answer/evidence/intelligence response.

Graph POST timeouts can leave an uncertain remote outcome; requests are not automatically retried. Check Teams before retrying. The confirmation workflow is separate from internal application-group sharing.

## Rollout

Run `alembic upgrade head` from app/backend, restart backend and frontend. Configure the documented Graph permissions and a dedicated GRAPH_TOKEN_ENCRYPTION_KEY, then sign in through Entra again. Web research is optional and defaults to none. Follow docs/MICROSOFT_GRAPH_PERMISSIONS.md and docs/SEARCH_INTELLIGENCE.md. Existing private .env values were not modified.
