"""`SearchProvider` abstraction — the pgvector/Postgres-full-text replacement.

Transcript chunks and their embeddings live here, never in the relational
database (see db/models.py's module-level note and
docs/MIGRATION_FROM_POSTGRES.md). Business logic (retrieval_agent.py,
discussion_agent.py, the meetings router) depends on this interface, never
directly on Azure SDK/REST calls — per the refinement's explicit requirement.

Two implementations:
  - `retrieval.memory_search.InMemorySearchProvider` — a real, working,
    in-process implementation used for local development and tests. It is
    NOT Azure AI Search and is never presented as such.
  - `retrieval.azure_search.AzureAISearchProvider` — a real Azure AI Search
    REST client, inert (raises `SearchNotConfiguredError`) without
    AZURE_SEARCH_ENDPOINT/AZURE_SEARCH_API_KEY/AZURE_SEARCH_INDEX.

Field names on `IndexableChunk`/`SearchHit` mirror the index schema in the
refinement prompt: id, tenant_id, meeting_id, meeting_join_id, meeting_title,
meeting_date, speaker_id, speaker_name, start_time, end_time, content,
content_type, chunk_index, source, document_id, embedding.

Historical-import upgrade: also carries `source_file`, `relative_path`,
`file_type`, `document_type`, `page_number`, `sheet_name`, `slide_number`,
`section` — the same fields transcript chunks and every non-transcript
document chunk (Word/Excel/PDF/PowerPoint/CSV/text) are indexed with, so
citations can point back to a page/sheet/slide/section as accurately as
they point back to a speaker/timestamp. See docs/HISTORICAL_IMPORT.md.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class IndexableChunk:
    id: str
    tenant_id: str
    meeting_id: str
    meeting_title: str
    content: str
    chunk_index: int
    start_time: float
    end_time: float
    document_id: str
    meeting_join_id: str | None = None
    meeting_date: str | None = None
    speaker_id: str | None = None
    speaker_name: str | None = None
    content_type: str = "transcript_chunk"
    source: str = "graph"
    embedding: list[float] | None = None
    # Historical-import fields — None/"" for a live Teams transcript chunk.
    source_file: str | None = None
    relative_path: str | None = None
    file_type: str = "vtt"
    document_type: str = "transcript"
    page_number: int | None = None
    sheet_name: str | None = None
    slide_number: int | None = None
    section: str | None = None


@dataclass
class SearchHit:
    id: str
    meeting_id: str
    content: str
    chunk_index: int
    start_time: float
    end_time: float
    score: float = 0.0
    speaker_name: str | None = None
    vector_rank: int | None = None
    keyword_rank: int | None = None
    source_file: str | None = None
    relative_path: str | None = None
    file_type: str = "vtt"
    document_type: str = "transcript"
    page_number: int | None = None
    sheet_name: str | None = None
    slide_number: int | None = None
    section: str | None = None

    # Backward-compatible aliases matching the pre-refactor `TranscriptChunk`
    # ORM attribute names, so `agents/answer_agent.py`, `agents/discussion_agent.py`
    # and `api/routers/meetings.py` need no changes beyond the import swap.
    @property
    def speaker(self) -> str | None:
        return self.speaker_name

    @property
    def start_seconds(self) -> float:
        return self.start_time

    @property
    def end_seconds(self) -> float:
        return self.end_time

    @property
    def text(self) -> str:
        return self.content


class SearchNotConfiguredError(RuntimeError):
    """Raised by a provider that requires configuration/credentials it doesn't have."""


class SearchProvider(ABC):
    @abstractmethod
    async def index_chunks(self, chunks: list[IndexableChunk]) -> None:
        """Upsert (index or replace) a batch of chunks, all belonging to one meeting."""

    @abstractmethod
    async def delete_meeting(self, *, tenant_id: str, meeting_id: str) -> None:
        """Remove every indexed chunk for a meeting (e.g. before re-indexing)."""

    @abstractmethod
    async def chunks_for_meeting(self, *, tenant_id: str, meeting_id: str) -> list[SearchHit]:
        """All chunks for one meeting, in chunk_index order — powers the raw source browser."""

    @abstractmethod
    async def keyword_search(
        self, *, tenant_id: str, meeting_ids: list[str], query: str, speaker: str | None = None, top_k: int
    ) -> list[SearchHit]: ...

    @abstractmethod
    async def vector_search(
        self, *, tenant_id: str, meeting_ids: list[str], vector: list[float], speaker: str | None = None, top_k: int
    ) -> list[SearchHit]: ...

    @abstractmethod
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
        """Combined keyword + vector retrieval. `tenant_id` and `meeting_ids`
        are mandatory, enforced filters — never optional, never trusted from
        anywhere but server-side authorization (see security/authz.py)."""
