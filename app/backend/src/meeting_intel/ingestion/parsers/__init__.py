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

_REGISTRY: dict[str, type[DocumentParser]] = {
    "vtt": VTTParser,
    "txt": TextParser,
    "docx": WordParser,
    "doc": WordParser,  # parse() itself raises UnsupportedFileError for real .doc content
    "xlsx": ExcelParser,
    "xls": ExcelParser,  # parse() itself raises UnsupportedFileError for real .xls content
    "pdf": PDFParser,
    "pptx": PowerPointParser,
    "csv": CSVParser,
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
