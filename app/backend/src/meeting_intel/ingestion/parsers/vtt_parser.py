"""Wraps the existing `transcript_parser.parse_vtt` + `chunker.chunk_cues` —
does not duplicate VTT parsing logic. Every historical `.vtt` file goes
through the exact same speaker/timestamp extraction as a live Teams
transcript loaded via Graph or manual paste.
"""
from __future__ import annotations

from meeting_intel.ingestion.chunker import chunk_cues
from meeting_intel.ingestion.documents import NormalizedDocument, ParseResult
from meeting_intel.ingestion.parsers.base import DocumentParser
from meeting_intel.ingestion.transcript_parser import parse_vtt


class VTTParser(DocumentParser):
    document_type = "transcript"

    def parse(
        self, *, content: bytes, filename: str, relative_path: str, tenant_id: str,
        meeting_id: str | None, title: str, document_id_prefix: str,
    ) -> ParseResult:
        try:
            raw = content.decode("utf-8")
        except UnicodeDecodeError:
            raw = content.decode("utf-8", errors="replace")

        cues = parse_vtt(raw)
        if not cues:
            return ParseResult(warnings=["No transcript cues found (empty or non-WebVTT content)."])

        chunks = chunk_cues(cues)
        documents = [
            NormalizedDocument(
                document_id=f"{document_id_prefix}:{chunk.chunk_index}",
                tenant_id=tenant_id,
                meeting_id=meeting_id,
                title=title,
                source_file=filename,
                relative_path=relative_path,
                file_type="vtt",
                document_type=self.document_type,
                content=chunk.text,
                speaker=chunk.speaker,
                start_time=chunk.start_seconds,
                end_time=chunk.end_seconds,
            )
            for chunk in chunks
        ]
        return ParseResult(documents=documents)
