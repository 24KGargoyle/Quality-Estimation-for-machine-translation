"""Real Azure AI Search REST client — the Postgres-free RAG refinement's
production `SearchProvider`. No SDK dependency added (`azure-search-documents`
was deliberately skipped; the REST surface used here is small, stable, and
`httpx` — already a dependency for Microsoft Graph — covers it, per the
"don't add a dependency an existing one already covers" rule).

Inert without AZURE_SEARCH_ENDPOINT/AZURE_SEARCH_API_KEY/AZURE_SEARCH_INDEX —
raises `SearchNotConfiguredError` before any HTTP call, never fabricates a
search result. Vector dimensions come from
`settings.azure_openai_embedding_dimensions` when the Azure OpenAI embedding
provider is active, or `settings.embedding_dim` for the local embedding
model — never hard-coded, matching whichever provider is actually configured
(see providers.py).

Query ranking uses Azure AI Search's own native hybrid + semantic ranking
(vector search + full-text + `queryType=semantic`), not a local RRF fusion —
per the refinement's explicit preference for native Azure ranking over
custom logic.

Tenant/meeting isolation is enforced with a server-built, OData-escaped
`filter` on every query — never a post-filter over unscoped results, and
`tenant_id`/`meeting_ids` are always the caller's already-authorized values
(see security/authz.py), never trusted from the request body directly.
"""
from __future__ import annotations

import logging

import httpx

from meeting_intel.config import get_settings
from .search_provider import IndexableChunk, SearchHit, SearchNotConfiguredError, SearchProvider

logger = logging.getLogger("meeting_intel.retrieval.azure_search")

API_VERSION = "2024-07-01"
PAGE_SIZE = 1000


def _escape_odata(value: str) -> str:
    return value.replace("'", "''")


class AzureAISearchProvider(SearchProvider):
    def __init__(self) -> None:
        self.settings = get_settings()

    def _require_configured(self) -> None:
        if not self.settings.search_configured:
            raise SearchNotConfiguredError(
                "Azure AI Search is not configured. Set AZURE_SEARCH_ENDPOINT, "
                "AZURE_SEARCH_API_KEY, AZURE_SEARCH_INDEX."
            )

    def _vector_dimensions(self) -> int:
        if self.settings.embedding_provider == "azure_openai":
            if not self.settings.azure_openai_embedding_dimensions:
                raise SearchNotConfiguredError(
                    "Set AZURE_OPENAI_EMBEDDING_DIMENSIONS before using Azure AI Search "
                    "with the azure_openai embedding provider."
                )
            return self.settings.azure_openai_embedding_dimensions
        return self.settings.embedding_dim

    def _url(self, path: str) -> str:
        return f"{self.settings.azure_search_endpoint.rstrip('/')}/indexes/{self.settings.azure_search_index}{path}?api-version={API_VERSION}"

    async def _request(self, method: str, path: str, json_body: dict | None = None) -> dict:
        self._require_configured()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method, self._url(path),
                    headers={"api-key": self.settings.azure_search_api_key, "Content-Type": "application/json"},
                    json=json_body,
                )
            response.raise_for_status()
            return response.json() if response.content else {}
        except SearchNotConfiguredError:
            raise
        except Exception:
            logger.warning("azure_search_request_failed")
            raise SearchNotConfiguredError(
                "Azure AI Search request failed; check endpoint/key/index configuration"
            ) from None

    async def ensure_index(self) -> None:
        """Idempotent create-or-update, called before the first use."""
        dimensions = self._vector_dimensions()
        body = {
            "name": self.settings.azure_search_index,
            "fields": [
                {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
                {"name": "tenant_id", "type": "Edm.String", "filterable": True},
                {"name": "meeting_id", "type": "Edm.String", "filterable": True},
                {"name": "meeting_join_id", "type": "Edm.String", "filterable": True},
                {"name": "meeting_title", "type": "Edm.String", "searchable": True, "filterable": True, "sortable": True},
                {"name": "meeting_date", "type": "Edm.String", "filterable": True, "sortable": True},
                {"name": "speaker_id", "type": "Edm.String", "filterable": True},
                {"name": "speaker_name", "type": "Edm.String", "searchable": True, "filterable": True},
                {"name": "start_time", "type": "Edm.Double", "filterable": True, "sortable": True},
                {"name": "end_time", "type": "Edm.Double", "filterable": True, "sortable": True},
                {"name": "content", "type": "Edm.String", "searchable": True},
                {"name": "content_type", "type": "Edm.String", "filterable": True},
                {"name": "chunk_index", "type": "Edm.Int32", "filterable": True, "sortable": True},
                {"name": "source", "type": "Edm.String", "filterable": True},
                {"name": "document_id", "type": "Edm.String", "filterable": True},
                # Historical-import fields — see docs/HISTORICAL_IMPORT.md. Populated for every
                # non-transcript document chunk; left at their defaults for live transcript chunks.
                {"name": "source_file", "type": "Edm.String", "searchable": True, "filterable": True},
                {"name": "relative_path", "type": "Edm.String", "filterable": True},
                {"name": "file_type", "type": "Edm.String", "filterable": True, "facetable": True},
                {"name": "document_type", "type": "Edm.String", "filterable": True, "facetable": True},
                {"name": "page_number", "type": "Edm.Int32", "filterable": True, "sortable": True},
                {"name": "sheet_name", "type": "Edm.String", "filterable": True},
                {"name": "slide_number", "type": "Edm.Int32", "filterable": True, "sortable": True},
                {"name": "section", "type": "Edm.String", "searchable": True, "filterable": True},
                {"name": "embedding", "type": "Collection(Edm.Single)", "searchable": True,
                 "dimensions": dimensions, "vectorSearchProfile": "default-profile"},
            ],
            "vectorSearch": {
                "algorithms": [{"name": "default-hnsw", "kind": "hnsw", "hnswParameters": {"metric": "cosine"}}],
                "profiles": [{"name": "default-profile", "algorithm": "default-hnsw"}],
            },
            "semanticSearch": {
                "defaultConfiguration": self.settings.azure_search_semantic_config,
                "configurations": [{
                    "name": self.settings.azure_search_semantic_config,
                    "prioritizedFields": {
                        "titleField": {"fieldName": "meeting_title"},
                        "contentFields": [{"fieldName": "content"}],
                        "keywordsFields": [{"fieldName": "speaker_name"}],
                    },
                }],
            },
        }
        await self._request("PUT", "", body)

    async def index_chunks(self, chunks: list[IndexableChunk]) -> None:
        if not chunks:
            return
        await self.ensure_index()
        actions = [
            {
                "@search.action": "mergeOrUpload",
                "id": c.id,
                "tenant_id": c.tenant_id,
                "meeting_id": c.meeting_id,
                "meeting_join_id": c.meeting_join_id or "",
                "meeting_title": c.meeting_title,
                "meeting_date": c.meeting_date or "",
                "speaker_id": c.speaker_id or "",
                "speaker_name": c.speaker_name or "",
                "start_time": c.start_time,
                "end_time": c.end_time,
                "content": c.content,
                "content_type": c.content_type,
                "chunk_index": c.chunk_index,
                "source": c.source,
                "document_id": c.document_id,
                "source_file": c.source_file or "",
                "relative_path": c.relative_path or "",
                "file_type": c.file_type,
                "document_type": c.document_type,
                "sheet_name": c.sheet_name or "",
                "section": c.section or "",
                **({"page_number": c.page_number} if c.page_number is not None else {}),
                **({"slide_number": c.slide_number} if c.slide_number is not None else {}),
                **({"embedding": c.embedding} if c.embedding else {}),
            }
            for c in chunks
        ]
        await self._request("POST", "/docs/index", {"value": actions})

    async def _ids_for_meeting(self, tenant_id: str, meeting_id: str) -> list[str]:
        ids: list[str] = []
        skip = 0
        while True:
            data = await self._request("POST", "/docs/search", {
                "search": "*",
                "filter": f"tenant_id eq '{_escape_odata(tenant_id)}' and meeting_id eq '{_escape_odata(meeting_id)}'",
                "select": "id", "top": PAGE_SIZE, "skip": skip,
            })
            rows = data.get("value", [])
            ids.extend(row["id"] for row in rows)
            if len(rows) < PAGE_SIZE:
                return ids
            skip += PAGE_SIZE

    async def delete_meeting(self, *, tenant_id: str, meeting_id: str) -> None:
        ids = await self._ids_for_meeting(tenant_id, meeting_id)
        if not ids:
            return
        await self._request("POST", "/docs/index", {"value": [{"@search.action": "delete", "id": i} for i in ids]})

    @staticmethod
    def _hit(row: dict) -> SearchHit:
        return SearchHit(
            id=row["id"], meeting_id=row["meeting_id"], content=row.get("content", ""),
            chunk_index=row.get("chunk_index", 0), start_time=row.get("start_time", 0.0),
            end_time=row.get("end_time", 0.0), speaker_name=row.get("speaker_name") or None,
            score=row.get("@search.rerankerScore", row.get("@search.score", 0.0)) or 0.0,
            source_file=row.get("source_file") or None, relative_path=row.get("relative_path") or None,
            file_type=row.get("file_type") or "vtt", document_type=row.get("document_type") or "transcript",
            page_number=row.get("page_number"), sheet_name=row.get("sheet_name") or None,
            slide_number=row.get("slide_number"), section=row.get("section") or None,
        )

    async def chunks_for_meeting(self, *, tenant_id: str, meeting_id: str) -> list[SearchHit]:
        data = await self._request("POST", "/docs/search", {
            "search": "*",
            "filter": f"tenant_id eq '{_escape_odata(tenant_id)}' and meeting_id eq '{_escape_odata(meeting_id)}'",
            "orderby": "chunk_index asc", "top": PAGE_SIZE,
        })
        return [self._hit(row) for row in data.get("value", [])]

    def _scope_filter(self, tenant_id: str, meeting_ids: list[str], speaker: str | None) -> str:
        # Mandatory tenant_id + meeting_id filters (refinement §7) — never
        # optional, and only ever built from server-verified values.
        meeting_clause = " or ".join(f"meeting_id eq '{_escape_odata(m)}'" for m in meeting_ids)
        parts = [f"tenant_id eq '{_escape_odata(tenant_id)}'", f"({meeting_clause})"]
        if speaker:
            parts.append(f"speaker_name eq '{_escape_odata(speaker)}'")
        return " and ".join(parts)

    async def keyword_search(
        self, *, tenant_id: str, meeting_ids: list[str], query: str, speaker: str | None = None, top_k: int
    ) -> list[SearchHit]:
        if not meeting_ids:
            return []
        data = await self._request("POST", "/docs/search", {
            "search": query, "queryType": "simple",
            "filter": self._scope_filter(tenant_id, meeting_ids, speaker), "top": top_k,
        })
        return [self._hit(row) for row in data.get("value", [])]

    async def vector_search(
        self, *, tenant_id: str, meeting_ids: list[str], vector: list[float], speaker: str | None = None, top_k: int
    ) -> list[SearchHit]:
        if not meeting_ids:
            return []
        data = await self._request("POST", "/docs/search", {
            "search": "*", "filter": self._scope_filter(tenant_id, meeting_ids, speaker), "top": top_k,
            "vectorQueries": [{"kind": "vector", "vector": vector, "fields": "embedding", "k": top_k}],
        })
        return [self._hit(row) for row in data.get("value", [])]

    async def hybrid_search(
        self,
        *,
        tenant_id: str,
        meeting_ids: list[str],
        query: str,
        vector: list[float] | None = None,
        speaker: str | None = None,
        top_k: int,
        document_id: str | None = None,
    ) -> list[SearchHit]:
        if not meeting_ids or not query.strip():
            return []
        body = {
            "search": query,
            "queryType": "semantic" if self.settings.azure_search_semantic_config else "simple",
            "semanticConfiguration": self.settings.azure_search_semantic_config,
            "filter": self._scope_filter(tenant_id, meeting_ids, speaker),
            "top": top_k,
        }
        if document_id is not None:
            body["filter"] += f" and document_id eq '{_escape_odata(document_id)}'"
        if vector is not None:
            body["vectorQueries"] = [{"kind": "vector", "vector": vector, "fields": "embedding", "k": top_k}]
        data = await self._request("POST", "/docs/search", body)
        return [self._hit(row) for row in data.get("value", [])]


_provider: AzureAISearchProvider | None = None


def get_azure_search_provider() -> AzureAISearchProvider:
    global _provider
    if _provider is None:
        _provider = AzureAISearchProvider()
    return _provider
