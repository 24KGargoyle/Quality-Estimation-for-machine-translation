"""Query understanding for evidence-first search (§1 of the Search
Intelligence upgrade): person/entity detection and a lightweight intent
classification, built on top of the meeting router's existing speaker-filter
and cross-meeting detection rather than duplicating that logic.

No ML/NER model is used — this is deliberately simple, deterministic
substring/keyword matching against known names and a short trigger-word list.
It is accurate enough for "what did X say" style questions (matching a real
participant/speaker name) without the cost, latency, or opacity of an LLM
call just to parse the question.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from meeting_intel.agents.meeting_router import extract_speaker_filter, is_cross_meeting_query

QueryIntent = Literal["person", "document", "topic", "generic"]

_DOCUMENT_INTENT_WORDS = {
    "document", "docx", "pdf", "xlsx", "spreadsheet", "presentation", "pptx", "slide", "sheet", "file",
}
_PERSON_INTENT_PATTERNS = ("say", "said", "mention", "think", "responsible", "role", "agree", "decide", "who is")


@dataclass
class QueryUnderstanding:
    query: str
    person: str | None
    all_mentioned_people: list[str]
    intent: QueryIntent
    is_cross_meeting: bool


def find_mentioned_names(query: str, known_names: list[str]) -> list[str]:
    """Every known name mentioned in the query, in order of first
    appearance. Matches on a word boundary (`\\b`), so a name followed by
    punctuation — "Bob's plan", "Alice," — still matches; a naive
    substring/`.split()` membership check would miss these."""
    q = query.lower()
    matches: list[tuple[int, str]] = []
    for name in {n for n in known_names if n}:
        lname = name.lower()
        parts = lname.split()
        match = re.search(rf"\b{re.escape(lname)}\b", q)
        if not match and parts:
            match = re.search(rf"\b{re.escape(parts[0])}\b", q)
        if match:
            matches.append((match.start(), name))
    matches.sort(key=lambda pair: pair[0])
    # de-duplicate while preserving order (a full name and its first name
    # both matching should only surface the fuller name once)
    seen: set[str] = set()
    ordered: list[str] = []
    for _, name in matches:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _classify_intent(query: str, person: str | None) -> QueryIntent:
    q = query.lower()
    if person and any(p in q for p in _PERSON_INTENT_PATTERNS):
        return "person"
    if any(w in q for w in _DOCUMENT_INTENT_WORDS):
        return "document"
    if person:
        return "person"
    return "topic" if len(q.split()) > 2 else "generic"


def understand_query(query: str, participant_names: list[str]) -> QueryUnderstanding:
    person = extract_speaker_filter(query, participant_names)
    mentioned = find_mentioned_names(query, participant_names)
    return QueryUnderstanding(
        query=query,
        person=person,
        all_mentioned_people=mentioned,
        intent=_classify_intent(query, person),
        is_cross_meeting=is_cross_meeting_query(query),
    )
