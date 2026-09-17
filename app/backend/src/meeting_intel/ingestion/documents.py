"""The Common Document Model: every parser (VTT, Word, Excel, PDF, PowerPoint,
CSV, plain text) normalizes its file into a list of these, so downstream
chunking/embedding/indexing (`ingestion/historical_import.py`) and citation
display never need to know which parser produced a given piece of content.

`document_type` values: transcript, supporting_document, spreadsheet,
presentation, reference_document, unknown.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class NormalizedDocument:
    document_id: str
    tenant_id: str
    title: str
    source_file: str
    relative_path: str
    file_type: str
    document_type: str
    content: str
    meeting_id: str | None = None
    speaker: str | None = None
    start_time: float | None = None
    end_time: float | None = None
    page_number: int | None = None
    sheet_name: str | None = None
    slide_number: int | None = None
    section: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseResult:
    """What a parser hands back for one input file."""

    documents: list[NormalizedDocument] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class UnsupportedFileError(ValueError):
    """Raised by a parser when the file's content can't be safely parsed
    (corrupted, empty of extractable text, legacy format without a safe
    converter, etc.) — the import pipeline reports this file as `skipped`
    rather than failing the whole batch."""
