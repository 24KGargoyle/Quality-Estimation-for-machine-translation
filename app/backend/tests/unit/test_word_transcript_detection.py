import io

import pytest
from docx import Document

from meeting_intel.ingestion.parsers.word_parser import WordParser


@pytest.mark.parametrize("filename,text,expected", [
    ("Video Transcript_Final.docx", "Alice: Hello", "transcript"),
    ("notes.docx", "Transcript\nAlice: Hello", "transcript"),
    ("notes.docx", "Alice 0:01\nHello\nBob 0:05\nHi", "transcript"),
    ("playbook.docx", "Please review the transcript before approval.", "supporting_document"),
])
def test_word_transcript_classification(filename, text, expected):
    doc = Document()
    for line in text.splitlines():
        doc.add_paragraph(line)
    stream = io.BytesIO()
    doc.save(stream)
    result = WordParser().parse(
        content=stream.getvalue(), filename=filename, relative_path=filename,
        tenant_id="t", meeting_id="m", title="Meeting", document_id_prefix="doc",
    )
    assert result.documents
    assert all(chunk.document_type == expected for chunk in result.documents)
    assert all(chunk.start_time is None for chunk in result.documents)
