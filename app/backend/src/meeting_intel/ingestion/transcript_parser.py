"""Parse Microsoft Teams meeting transcripts (WebVTT) into speaker-attributed cues.

Teams transcript VTT cues look like:

    WEBVTT

    00:00:00.000 --> 00:00:05.230
    <v Chetan Kumar>We should confirm the CrewAI requirement first.</v>

Every parsed cue keeps its speaker name and start/end offsets in seconds so
that metadata is never lost downstream (chunking, embedding, citations).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_TIME_RE = re.compile(
    r"(?P<h1>\d{2}):(?P<m1>\d{2}):(?P<s1>\d{2})[.,](?P<ms1>\d{1,3})\s*-->\s*"
    r"(?P<h2>\d{2}):(?P<m2>\d{2}):(?P<s2>\d{2})[.,](?P<ms2>\d{1,3})"
)
_VOICE_RE = re.compile(r"<v\s+([^>]+)>(.*?)(</v>)?$", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class TranscriptCue:
    speaker: str | None
    start_seconds: float
    end_seconds: float
    text: str


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    ms_padded = (ms + "000")[:3]
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms_padded) / 1000.0


def parse_vtt(raw: str) -> list[TranscriptCue]:
    lines = raw.replace("\r\n", "\n").split("\n")
    cues: list[TranscriptCue] = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = _TIME_RE.search(line)
        if match:
            start = _to_seconds(match["h1"], match["m1"], match["s1"], match["ms1"])
            end = _to_seconds(match["h2"], match["m2"], match["s2"], match["ms2"])
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip() != "" and not _TIME_RE.search(lines[i]):
                text_lines.append(lines[i])
                i += 1
            raw_text = " ".join(text_lines).strip()
            speaker = None
            voice_match = _VOICE_RE.match(raw_text)
            if voice_match:
                speaker = voice_match.group(1).strip()
                text = voice_match.group(2).strip()
            else:
                text = raw_text
            text = _TAG_RE.sub("", text).strip()
            if text:
                cues.append(TranscriptCue(speaker=speaker, start_seconds=start, end_seconds=end, text=text))
        else:
            i += 1

    return cues
