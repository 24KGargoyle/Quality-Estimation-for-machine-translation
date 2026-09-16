"""Grounded answer generation: Retrieval Agent -> Answer Agent.

Grounding rule: the model is only allowed to answer from the excerpts it was
given, and cites them as [S1], [S2]... We parse those citation markers back
against the exact excerpts we sent (never trusting the model to invent a
speaker/timestamp) to build the `AISource` records shown to the user.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.agents.prompts import build_meeting_qa_messages
from meeting_intel.agents.retrieval_agent import resolve_scope_and_retrieve
from meeting_intel.db.models import Meeting, User
from meeting_intel.llm.client import LLMNotConfiguredError
from meeting_intel.providers import get_llm_provider
from meeting_intel.retrieval.hybrid_search import RetrievedChunk

INSUFFICIENT_EVIDENCE_MSG = "I couldn't find enough evidence in this meeting to answer that confidently."
LLM_UNAVAILABLE_MSG = (
    "The AI model is not configured in this environment (missing ANTHROPIC_API_KEY), "
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


@dataclass
class AnswerResult:
    text: str
    sources: list[SourceCitation] = field(default_factory=list)
    evidence_sufficient: bool = True
    cross_meeting: bool = False
    speaker_filter: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    retrieval_query: str | None = None


def _parse_citations(text: str, chunks: list[RetrievedChunk]) -> list[SourceCitation]:
    cited_indices = sorted({int(m) for m in _CITATION_RE.findall(text)})
    sources = []
    for idx in cited_indices:
        if 1 <= idx <= len(chunks):
            rc = chunks[idx - 1]
            sources.append(
                SourceCitation(
                    chunk=rc.chunk,
                    excerpt=rc.chunk.text,
                    speaker=rc.chunk.speaker,
                    start_seconds=rc.chunk.start_seconds,
                    end_seconds=rc.chunk.end_seconds,
                    score=rc.score,
                )
            )
    # If the model didn't cite anything but excerpts were used, fall back to top excerpt
    # so the user still sees where the answer likely came from.
    if not sources and chunks:
        rc = chunks[0]
        sources.append(
            SourceCitation(
                chunk=rc.chunk,
                excerpt=rc.chunk.text,
                speaker=rc.chunk.speaker,
                start_seconds=rc.chunk.start_seconds,
                end_seconds=rc.chunk.end_seconds,
                score=rc.score,
            )
        )
    return sources


async def answer_question(
    db: AsyncSession, *, meeting: Meeting, user: User, history: list[dict], question: str
) -> AnswerResult:
    chunks, speaker, cross_meeting = await resolve_scope_and_retrieve(
        db, meeting=meeting, user=user, question=question
    )

    if not chunks:
        return AnswerResult(
            text=INSUFFICIENT_EVIDENCE_MSG,
            evidence_sufficient=False,
            cross_meeting=cross_meeting,
            speaker_filter=speaker,
            retrieval_query=question,
        )

    system, messages = build_meeting_qa_messages(history=history, excerpts=chunks, question=question)
    try:
        result = await get_llm_provider().complete(system=system, messages=messages)
    except LLMNotConfiguredError:
        return AnswerResult(
            text=LLM_UNAVAILABLE_MSG,
            sources=_parse_citations("", chunks)[:0],
            evidence_sufficient=False,
            cross_meeting=cross_meeting,
            speaker_filter=speaker,
            retrieval_query=question,
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
        retrieval_query=question,
    )
