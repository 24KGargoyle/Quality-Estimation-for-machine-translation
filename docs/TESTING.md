# Validation

Run the backend suite from `app/backend` with `python -m pytest tests -q`. Use the repository Python environment. Tests create and migrate a temporary SQLite database, clear rows between tests, and reset the in-memory search provider.

The test environment explicitly selects local embeddings and disables live LLM, Graph and web services. Cached sentence-transformer assets are required; Hugging Face and Transformers run offline. A session fixture blocks non-loopback socket connections and all asynchronous network connection creation. Loopback socket pairs remain allowed for Windows asyncio internals. Graph/Azure Search/web tests use mocked HTTP. Do not remove the network guard to resolve a missing local model cache.

Coverage includes authorization and tenant isolation; imports and document-scoped retrieval; prompt construction and citations; person query understanding and reranking; evidence-based related items; optional web triggering; attendance identity resolution; exact Teams chat matching; creation confirmation and caller inclusion; saved-message sending; chat membership revalidation; internal group membership; feedback and discussion workflows.

Frontend checks: `npx tsc --noEmit`, `npm run lint`, `npm run build` from `app/frontend`. Browser interaction and live Azure SQL/Search/OpenAI/Graph validation are separate deployment checks and must not be inferred from mocked tests or a successful build.

See `audits/POST_SEARCH_TEAMS_COLLABORATION_AUDIT.md` for the actual results of this implementation pass, including failures and limitations.
