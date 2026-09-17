"""`DocumentParser` interface — one implementation per file format, all
returning the same `ParseResult` (a list of `NormalizedDocument`). Business
logic (the historical import pipeline) depends only on this interface via
`ParserFactory.get_parser()`, never on a specific format library directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from meeting_intel.ingestion.documents import ParseResult


class DocumentParser(ABC):
    #: document_type assigned to every NormalizedDocument this parser produces,
    #: unless a subclass overrides it per-document (e.g. VTTParser -> "transcript").
    document_type: str = "unknown"

    @abstractmethod
    def parse(
        self,
        *,
        content: bytes,
        filename: str,
        relative_path: str,
        tenant_id: str,
        meeting_id: str | None,
        title: str,
        document_id_prefix: str,
    ) -> ParseResult:
        """Parse raw file bytes into normalized documents.

        Must never raise for a merely-empty or content-free file — return an
        empty `ParseResult` with a warning instead. Only raise
        `meeting_intel.ingestion.documents.UnsupportedFileError` for a file
        this parser cannot safely handle at all (corrupted beyond recovery,
        a legacy format with no safe converter, password-protected, etc.) —
        the import pipeline reports that as a skipped/failed file without
        aborting the rest of the batch.
        """
