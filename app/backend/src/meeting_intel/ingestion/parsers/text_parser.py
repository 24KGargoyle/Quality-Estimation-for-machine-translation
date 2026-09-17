from __future__ import annotations

from meeting_intel.ingestion.documents import NormalizedDocument, ParseResult
from meeting_intel.ingestion.parsers.base import DocumentParser
from meeting_intel.ingestion.parsers.textutil import split_text


class TextParser(DocumentParser):
    document_type = "supporting_document"

    def parse(
        self, *, content: bytes, filename: str, relative_path: str, tenant_id: str,
        meeting_id: str | None, title: str, document_id_prefix: str,
    ) -> ParseResult:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1", errors="replace")

        pieces = split_text(text)
        if not pieces:
            return ParseResult(warnings=["File contains no extractable text."])

        documents = [
            NormalizedDocument(
                document_id=f"{document_id_prefix}:{i}",
                tenant_id=tenant_id,
                meeting_id=meeting_id,
                title=title,
                source_file=filename,
                relative_path=relative_path,
                file_type="txt",
                document_type=self.document_type,
                content=piece,
            )
            for i, piece in enumerate(pieces)
        ]
        return ParseResult(documents=documents)
