"""Shared text-splitting helper for parsers whose natural unit (a paragraph,
a PDF page, a slide) can still be too long for one retrieval chunk. Splits on
paragraph/line boundaries where possible so a chunk never cuts a sentence in
an unrecoverable place more than necessary.
"""
from __future__ import annotations

DEFAULT_MAX_CHARS = 900


def split_text(text: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [text]

    buffer = ""
    for para in paragraphs:
        candidate = f"{buffer}\n\n{para}" if buffer else para
        if len(candidate) <= max_chars:
            buffer = candidate
            continue
        if buffer:
            pieces.append(buffer)
            buffer = ""
        if len(para) <= max_chars:
            buffer = para
        else:
            for i in range(0, len(para), max_chars):
                pieces.append(para[i : i + max_chars])
    if buffer:
        pieces.append(buffer)
    return pieces
