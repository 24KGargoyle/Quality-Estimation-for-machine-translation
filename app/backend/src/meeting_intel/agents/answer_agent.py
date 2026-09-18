"""Grounded answer generation: Retrieval Agent -> Answer Agent.

Grounding rule: the model is only allowed to answer from the excerpts it was
given, and cites them as [S1], [S2]... We parse those citation markers back
against the exact excerpts we sent (never trusting the model to invent a
speaker/timestamp) to build the `AISource` records shown to the user.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.agents.prompts import build_meeting_qa_messages
from meeting_intel.agents.retrieval_agent import resolve_scope_and_retrieve
from meeting_intel.db.models import Meeting, User
from meeting_intel.llm.client import LLMNotConfiguredError
from meeting_intel.providers import get_llm_provider
from meeting_intel.retrieval.hybrid_search import RetrievedChunk

INSUFFICIENT_EVIDENCE_MSG = "I couldn't find enough evidence in this meeting to answer that confidently."
LLM_UNAVAILABLE_MSG = (
    "The AI model is not configured in this environment (check the configured model provider), "
    "so I can't generate an answer right now. The retrieval below shows what evidence exists."
)

_CITATION_RE = re.compile(r"\[S(\d+)\]")


@dataclass
class SourceCitation:
    chunk: object
    excerpt: str
    speaker: str | None
    start_seconds: float
    end_seconds: float
    score: float
    source_file: str | None = None
    file_type: str = "vtt"
    document_type: str = "transcript"
    page_number: int | None = None
    sheet_name: str | None = None
    slide_number: int | None = None
    section: str | None = None


@dataclass
class AnswerResult:
    text: str
    sources: list[SourceCitation] = field(default_factory=list)
    evidence_sufficient: bool = True
    cross_meeting: bool = False
    speaker_filter: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    mentioned_people: list[str] = field(default_factory=list)
    retrieved_chunks: list[RetrievedChunk] = field(default_factory=list)
    retrieval_query: str | None = None


def _to_citation(rc: RetrievedChunk) -> SourceCitation:
    c = rc.chunk
    return SourceCitation(
        chunk=c, excerpt=c.text, speaker=c.speaker, start_seconds=c.start_seconds, end_seconds=c.end_seconds,
        score=rc.score, source_file=c.source_file, file_type=c.file_type, document_type=c.document_type,
        page_number=c.page_number, sheet_name=c.sheet_name, slide_number=c.slide_number, section=c.section,
    )


def _parse_citations(text: str, chunks: list[RetrievedChunk]) -> list[SourceCitation]:
    cited_indices = sorted({int(m) for m in _CITATION_RE.findall(text)})
    sources = [_to_citation(chunks[idx - 1]) for idx in cited_indices if 1 <= idx <= len(chunks)]
    # If the model didn't cite anything but excerpts were used, fall back to top excerpt
    # so the user still sees where the answer likely came from.
    if not sources and chunks:
        sources.append(_to_citation(chunks[0]))
    return sources


async def answer_question(
    db: AsyncSession, *, meeting: Meeting, user: User, history: list[dict], question: str, document=None
) -> AnswerResult:
    chunks, understanding = await resolve_scope_and_retrieve(
        db, meeting=meeting, user=user, question=question, document=document
    )

    # Bound the exact evidence shown to the model; never load a full transcript.
    bounded = []
    remaining = 18000
    for rc in chunks[:8]:
        content = rc.chunk.content[:min(3000, remaining)]
        if not content:
            break
        bounded.append(replace(rc, chunk=replace(rc.chunk, content=content)))
        remaining -= len(content)
    chunks = bounded
    speaker, cross_meeting = understanding.person, understanding.is_cross_meeting
    if not chunks:
        return AnswerResult(
            text=INSUFFICIENT_EVIDENCE_MSG,
            evidence_sufficient=False,
            cross_meeting=cross_meeting,
            speaker_filter=speaker,
            retrieval_query=question, mentioned_people=understanding.all_mentioned_people, retrieved_chunks=chunks,
        )

    system, messages = build_meeting_qa_messages(history=history, excerpts=chunks, question=question)
    if document is not None:
        system += (
            "\nThe user explicitly selected one document. In this request, 'this meeting', "
            "'this transcript', and 'this document' refer to that selected document's content. "
            "All provided excerpts are restricted to that document. Cite those excerpts."
        )
    try:
        result = await get_llm_provider().complete(system=system, messages=messages)
    except LLMNotConfiguredError:
        return AnswerResult(
            text=LLM_UNAVAILABLE_MSG,
            sources=[],
            evidence_sufficient=False,
            cross_meeting=cross_meeting,
            speaker_filter=speaker,
            retrieval_query=question, mentioned_people=understanding.all_mentioned_people, retrieved_chunks=chunks,
        )

    evidence_sufficient = INSUFFICIENT_EVIDENCE_MSG.lower() not in result.text.lower()
    sources = _parse_citations(result.text, chunks) if evidence_sufficient else []

    return AnswerResult(
        text=result.text,
        sources=sources,
        evidence_sufficient=evidence_sufficient,
        cross_meeting=cross_meeting,
        speaker_filter=speaker,
        model=result.model,
        latency_ms=result.latency_ms,
        retrieval_query=question, mentioned_people=understanding.all_mentioned_people, retrieved_chunks=chunks,
    )
