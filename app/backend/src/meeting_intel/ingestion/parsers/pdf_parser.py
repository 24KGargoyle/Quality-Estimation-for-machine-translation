"""PDF parsing via pypdf — per-page text extraction, preserving `page_number`
for citations. A scanned/image-only PDF has no extractable text layer; this
is reported as an unsupported file requiring OCR, never silently indexed as
an empty/successful document (see docs/HISTORICAL_IMPORT.md for the
documented, not-implemented-here, OCR path)."""
from __future__ import annotations

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from meeting_intel.ingestion.documents import NormalizedDocument, ParseResult, UnsupportedFileError
from meeting_intel.ingestion.parsers.base import DocumentParser
from meeting_intel.ingestion.parsers.textutil import split_text


class PDFParser(DocumentParser):
    document_type = "reference_document"

    def parse(
        self, *, content: bytes, filename: str, relative_path: str, tenant_id: str,
        meeting_id: str | None, title: str, document_id_prefix: str,
    ) -> ParseResult:
        try:
            reader = PdfReader(io.BytesIO(content))
        except (PdfReadError, ValueError) as exc:
            raise UnsupportedFileError(f"Could not open as a PDF: {exc}") from exc

        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise UnsupportedFileError("PDF is password-protected — cannot extract text.")

        documents: list[NormalizedDocument] = []
        pages_without_text = 0
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception:
                text = ""
            if not text:
                pages_without_text += 1
                continue
            for piece in split_text(text):
                documents.append(
                    NormalizedDocument(
                        document_id=f"{document_id_prefix}:{len(documents)}",
                        tenant_id=tenant_id,
                        meeting_id=meeting_id,
                        title=title,
                        source_file=filename,
                        relative_path=relative_path,
                        file_type="pdf",
                        document_type=self.document_type,
                        content=piece,
                        page_number=page_number,
                    )
                )

        if not documents:
            raise UnsupportedFileError(
                f"No extractable text found in {len(reader.pages)} page(s) — this looks like a "
                "scanned/image-based PDF, which requires OCR (not configured in this environment)."
            )

        warnings = []
        if pages_without_text:
            warnings.append(
                f"{pages_without_text} page(s) had no extractable text (possibly scanned/image content)."
            )
        return ParseResult(documents=documents, warnings=warnings)
