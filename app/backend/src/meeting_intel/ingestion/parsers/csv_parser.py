"""CSV parsing — header + rows, batched into row groups (never one giant
document for a large file)."""
from __future__ import annotations

import csv
import io

from meeting_intel.ingestion.documents import NormalizedDocument, ParseResult, UnsupportedFileError
from meeting_intel.ingestion.parsers.base import DocumentParser

ROWS_PER_CHUNK = 25


class CSVParser(DocumentParser):
    document_type = "spreadsheet"

    def parse(
        self, *, content: bytes, filename: str, relative_path: str, tenant_id: str,
        meeting_id: str | None, title: str, document_id_prefix: str,
    ) -> ParseResult:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1", errors="replace")

        try:
            reader = csv.reader(io.StringIO(text))
            rows = [row for row in reader if any(c.strip() for c in row)]
        except csv.Error as exc:
            raise UnsupportedFileError(f"Could not parse as CSV: {exc}") from exc

        if not rows:
            return ParseResult(warnings=["File contains no rows."])

        headers, data_rows = rows[0], rows[1:]
        if not data_rows:
            return ParseResult(warnings=["File contains a header row but no data rows."])

        documents: list[NormalizedDocument] = []
        for start in range(0, len(data_rows), ROWS_PER_CHUNK):
            batch = data_rows[start : start + ROWS_PER_CHUNK]
            lines = [f"File: {filename}", "", " | ".join(headers)]
            lines += [" | ".join(row) for row in batch]
            documents.append(
                NormalizedDocument(
                    document_id=f"{document_id_prefix}:{len(documents)}",
                    tenant_id=tenant_id,
                    meeting_id=meeting_id,
                    title=title,
                    source_file=filename,
                    relative_path=relative_path,
                    file_type="csv",
                    document_type=self.document_type,
                    content="\n".join(lines),
                    metadata={"row_start": start + 2, "row_end": start + 1 + len(batch)},
                )
            )
        return ParseResult(documents=documents)
