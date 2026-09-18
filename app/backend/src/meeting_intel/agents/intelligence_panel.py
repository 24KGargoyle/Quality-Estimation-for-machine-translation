"""Related Intelligence sidebar (Part 2 of the Search Intelligence upgrade):
related topics, documents, and people extracted from the *actual* retrieved
evidence and meeting roster — never invented — plus a conditionally
triggered, clearly-separated web research lookup (Part 3).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from meeting_intel.agents.prompts import source_label
from meeting_intel.retrieval.hybrid_search import RetrievedChunk, get_search_provider
from meeting_intel.web_research.provider import (
    WebResearchNotConfiguredError,
    WebResearchResult,
    extract_research_topic,
    get_web_research_provider,
    should_research_web,
)

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "did", "do", "does", "what", "who", "we", "us",
    "when", "where", "why", "how", "to", "of", "in", "on", "for", "and", "or", "about", "that",
    "this", "with", "from", "at", "as", "be", "been", "will", "would", "should", "could", "can",
    "i", "you", "he", "she", "it", "they", "them", "his", "her", "their", "our", "not", "have",
    "has had", "said", "say", "says", "think", "thinks", "meeting", "team", "discussed", "discuss",
}

TOPIC_MAX = 5
DOCUMENT_MAX = 5
PEOPLE_MAX = 8


@dataclass
class RelatedDocument:
    source_file: str
    document_type: str
    file_type: str
    location: str | None


@dataclass
class IntelligencePanel:
    related_topics: list[str] = field(default_factory=list)
    related_documents: list[RelatedDocument] = field(default_factory=list)
    related_people: list[str] = field(default_factory=list)
    ideas: list[str] = field(default_factory=list)
    web_research: WebResearchResult | None = None


def _extract_topics(chunks: list[RetrievedChunk]) -> list[str]:
    """Frequency-based keyword extraction over the retrieved evidence text
    only — every topic surfaced is a word that literally appears in what was
    retrieved, never a term the model or this code invents."""
    counts: dict[str, int] = {}
    original_casing: dict[str, str] = {}
    for rc in chunks:
        words = re.findall(r"[A-Za-z][A-Za-z0-9\-/]{2,}", rc.chunk.content)
        for w in words:
            key = w.lower()
            if key in _STOPWORDS or len(key) < 3:
                continue
            counts[key] = counts.get(key, 0) + 1
            # Prefer a capitalized rendering (likely a proper noun / product
            # name like "Azure", "API") when one appears anywhere.
            if w[0].isupper() and (key not in original_casing or not original_casing[key][0].isupper()):
                original_casing[key] = w
            elif key not in original_casing:
                original_casing[key] = w
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [original_casing[k] for k, _ in ranked[:TOPIC_MAX]]


def _location_of(c) -> str | None:
    if c.page_number is not None:
        return f"Page {c.page_number}"
    if c.sheet_name:
        return f"Sheet: {c.sheet_name}"
    if c.slide_number is not None:
        return f"Slide {c.slide_number}"
    if c.section:
        return f"Section: {c.section}"
    return None


async def _related_documents(
    *, tenant_id: str, meeting_id: str, exclude_source_files: set[str], terms: set[str]
) -> list[RelatedDocument]:
    all_chunks = await get_search_provider().chunks_for_meeting(tenant_id=tenant_id, meeting_id=meeting_id)
    seen: dict[str, RelatedDocument] = {}
    for c in all_chunks:
        if not c.source_file or c.source_file in exclude_source_files or c.source_file in seen:
            continue
        if not terms.intersection(re.findall(r"[a-z0-9]+", c.content.lower())):
            continue
        seen[c.source_file] = RelatedDocument(
            source_file=c.source_file, document_type=c.document_type, file_type=c.file_type,
            location=_location_of(c),
        )
        if len(seen) >= DOCUMENT_MAX:
            break
    return list(seen.values())


def _related_people(chunks: list[RetrievedChunk], participant_names: list[str], mentioned: list[str]) -> list[str]:
    people: list[str] = []
    text = " ".join(rc.chunk.content for rc in chunks).casefold()
    for name in [*mentioned, *participant_names]:
        if not re.search(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", text):
            continue
        if name and name not in people:
            people.append(name)
    for rc in chunks:
        speaker = rc.chunk.speaker
        if speaker and speaker not in people:
            people.append(speaker)
    return people[:PEOPLE_MAX]


def _generate_ideas(topics: list[str], documents: list[RelatedDocument], has_transcript_evidence: bool) -> list[str]:
    ideas: list[str] = []
    doc_types = {d.document_type for d in documents}

    if topics:
        ideas.append(f"What do the retrieved sources say about {topics[0]}?")
    if documents:
        ideas.append(f"Review {documents[0].source_file} for related detail")
    if has_transcript_evidence:
        ideas.append("Discuss this with the meeting participants")
    return ideas[:4]


async def build_intelligence_panel(
    *,
    tenant_id: str,
    meeting_id: str,
    question: str,
    chunks: list[RetrievedChunk],
    participant_names: list[str],
    mentioned_people: list[str],
    cited_source_files: set[str],
) -> IntelligencePanel:
    topics = _extract_topics(chunks)
    documents = await _related_documents(
        tenant_id=tenant_id, meeting_id=meeting_id, exclude_source_files=cited_source_files, terms={t.lower() for t in topics}
    )
    people = _related_people(chunks, participant_names, mentioned_people)
    has_transcript = any(rc.chunk.document_type == "transcript" for rc in chunks)
    ideas = _generate_ideas(topics, documents, has_transcript)

    web_research = None
    if should_research_web(question):
        topic = extract_research_topic(question)
        try:
            web_research = await get_web_research_provider().research(topic)
        except WebResearchNotConfiguredError as exc:
            web_research = WebResearchResult(configured=False, query=topic, results=[], note=str(exc))

    return IntelligencePanel(
        related_topics=topics, related_documents=documents, related_people=people,
        ideas=ideas, web_research=web_research,
    )
