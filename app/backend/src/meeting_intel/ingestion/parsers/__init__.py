"""`ParserFactory.get_parser(file_type)` — the single place that maps a file
extension to its `DocumentParser`. Every supported format is registered
here exactly once; nothing else in the codebase should instantiate a parser
directly."""
from __future__ import annotations

from meeting_intel.ingestion.parsers.base import DocumentParser
from meeting_intel.ingestion.parsers.csv_parser import CSVParser
from meeting_intel.ingestion.parsers.excel_parser import ExcelParser
from meeting_intel.ingestion.parsers.pdf_parser import PDFParser
from meeting_intel.ingestion.parsers.powerpoint_parser import PowerPointParser
from meeting_intel.ingestion.parsers.text_parser import TextParser
from meeting_intel.ingestion.parsers.vtt_parser import VTTParser
from meeting_intel.ingestion.parsers.word_parser import WordParser
from .extended import (EmailParser, RichTextParser, LegacyExcelParser, OfficeConversionParser,
                       MediaParser, MEDIA_EXTENSIONS, LEGACY_EXTENSIONS)

_REGISTRY: dict[str, type[DocumentParser]] = {
    "vtt": VTTParser,
    "txt": TextParser,
    "docx": WordParser,
    "doc": OfficeConversionParser,
    "xlsx": ExcelParser,
    "xls": LegacyExcelParser,
    "pdf": PDFParser,
    "pptx": PowerPointParser,
    "csv": CSVParser,
    "eml": EmailParser,
    "msg": EmailParser,
    "xlsm": ExcelParser,
    "pptm": PowerPointParser,
    "ppsx": PowerPointParser,
    **{ext: OfficeConversionParser for ext in LEGACY_EXTENSIONS},
    **{ext: MediaParser for ext in MEDIA_EXTENSIONS},
    **{ext: RichTextParser for ext in ('md', 'markdown', 'html', 'htm', 'rtf', 'json', 'xml', 'log')},
}

SUPPORTED_EXTENSIONS = sorted(_REGISTRY)


class ParserFactory:
    @staticmethod
    def get_parser(file_type: str) -> DocumentParser | None:
        cls = _REGISTRY.get(file_type.lower().lstrip("."))
        return cls() if cls else None

    @staticmethod
    def is_supported(file_type: str) -> bool:
        return file_type.lower().lstrip(".") in _REGISTRY
