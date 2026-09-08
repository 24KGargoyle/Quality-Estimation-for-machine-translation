"""Chunk transcript cues for embedding while preserving speaker + timestamp metadata.

Consecutive cues from the same speaker are merged into a single chunk up to
`max_chars`; a speaker change always starts a new chunk so a chunk's speaker
attribution is never ambiguous.
"""
from __future__ import annotations

from dataclasses import dataclass

from meeting_intel.ingestion.transcript_parser import TranscriptCue

DEFAULT_MAX_CHARS = 900


@dataclass
class TranscriptChunkData:
    chunk_index: int
    speaker: str | None
    start_seconds: float
    end_seconds: float
    text: str


def chunk_cues(cues: list[TranscriptCue], *, max_chars: int = DEFAULT_MAX_CHARS) -> list[TranscriptChunkData]:
    chunks: list[TranscriptChunkData] = []
    buffer_text: list[str] = []
    buffer_speaker: str | None = None
    buffer_start: float | None = None
    buffer_end: float | None = None

    def flush() -> None:
        nonlocal buffer_text, buffer_speaker, buffer_start, buffer_end
        if buffer_text:
            chunks.append(
                TranscriptChunkData(
                    chunk_index=len(chunks),
                    speaker=buffer_speaker,
                    start_seconds=buffer_start or 0.0,
                    end_seconds=buffer_end or 0.0,
                    text=" ".join(buffer_text).strip(),
                )
            )
        buffer_text = []
        buffer_speaker = None
        buffer_start = None
        buffer_end = None

    for cue in cues:
        same_speaker = cue.speaker == buffer_speaker
        would_overflow = sum(len(t) for t in buffer_text) + len(cue.text) > max_chars
        if buffer_text and (not same_speaker or would_overflow):
            flush()

        if not buffer_text:
            buffer_speaker = cue.speaker
            buffer_start = cue.start_seconds
        buffer_text.append(cue.text)
        buffer_end = cue.end_seconds

    flush()
    return chunks
