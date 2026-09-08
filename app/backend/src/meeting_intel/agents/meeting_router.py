"""Decides retrieval scope (single meeting vs. explicit cross-meeting) and speaker filter.

Strict meeting isolation (mandatory requirement): the default is always the
single current meeting. Cross-meeting retrieval only happens when the query
matches an explicit cross-meeting pattern — never implicitly.
"""
from __future__ import annotations

import re

_CROSS_MEETING_PATTERNS = [
    r"\bcompare\b.*\bmeeting",
    r"\back?ross meetings\b",
    r"\blast (week|meeting)'?s? meeting\b",
    r"\bprevious meeting(s)?\b",
    r"\bother meetings\b",
    r"\bearlier meeting(s)?\b",
    r"\ball meetings\b",
]


def is_cross_meeting_query(query: str) -> bool:
    q = query.lower()
    return any(re.search(p, q) for p in _CROSS_MEETING_PATTERNS)


def extract_speaker_filter(query: str, participant_names: list[str]) -> str | None:
    q = query.lower()
    for name in sorted({n for n in participant_names if n}, key=len, reverse=True):
        # match on first name or full name to catch "What did Chetan say..."
        parts = name.lower().split()
        if name.lower() in q or (parts and parts[0] in q.split()):
            return name
    return None
