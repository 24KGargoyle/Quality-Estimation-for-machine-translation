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
    db: AsyncSession, *, meeting: Meeting, user: User, history: list[dict], question: str, document=None, customer_id: str | None = None
) -> AnswerResult:
    chunks, understanding = await resolve_scope_and_retrieve(
        db, meeting=meeting, user=user, question=question, document=document, **({"customer_id": customer_id} if customer_id is not None else {})
    )
    return await answer_from_evidence(chunks=chunks, understanding=understanding, history=history,
                                      question=question, document=document)


async def answer_from_evidence(*, chunks, history, question, understanding=None, document=None,
                               instructions='', require_citations=False) -> AnswerResult:
    """Shared bounded generation for existing RAG and customer-scoped uploads."""
    from meeting_intel.agents.query_understanding import understand_query
    understanding = understanding or understand_query(question, [])

    from meeting_intel.agents.answer_focus import answer_intent, answer_rules, focused_procedures
    if answer_intent(question) == 'procedure':
        chunks = focused_procedures(chunks, question)
        require_citations = True
    instructions += '\n' + answer_rules(question)

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
            text=("The meeting documents do not provide a complete end-to-end procedure. No directly supported steps were found."
                  if answer_intent(question) == "procedure" else INSUFFICIENT_EVIDENCE_MSG),
            evidence_sufficient=False,
            cross_meeting=cross_meeting,
            speaker_filter=speaker,
            retrieval_query=question, mentioned_people=understanding.all_mentioned_people, retrieved_chunks=chunks,
        )

    from meeting_intel.agents.acronym_grounding import requested_acronym, definition_sentences, unsupported_expansions
    acronym = requested_acronym(question)
    if acronym:
        definitions = [(i, definition) for i, rc in enumerate(chunks, 1)
                       for definition in definition_sentences(rc.chunk.content, acronym)]
        mentions = [i for i, rc in enumerate(chunks, 1)
                    if re.search(r'\b' + re.escape(acronym) + r'\b', rc.chunk.content, re.I)]
        if definitions:
            text = "The retrieved documents state:\n" + "\n".join(
                f"- {definition} [S{i}]" for i, definition in definitions[:3])
        elif mentions:
            text = f"The retrieved documents mention {acronym}, but do not define what it stands for. [S{mentions[0]}]"
        else:
            text = f"I could not verify a definition of {acronym} in the retrieved documents."
        if any(unsupported_expansions(m.get('content', ''), '\n'.join(c.chunk.content for c in chunks))
               for m in history if m.get('role') == 'assistant' and acronym in m.get('content', '')):
            text += " My earlier acronym expansion was not supported by these sources and should not be relied on."
        return AnswerResult(text=text, sources=_parse_citations(text, chunks) if mentions or definitions else [],
                            retrieved_chunks=chunks, retrieval_query=question, evidence_sufficient=True,
                            model='source-definition', cross_meeting=cross_meeting, speaker_filter=speaker)

    system, messages = build_meeting_qa_messages(history=history, excerpts=chunks, question=question)
    if instructions:
        system += '\n' + instructions
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

    # Reject unsupported acronym expansions even when the model supplied citations.
    if unsupported_expansions(result.text, '\n'.join(rc.chunk.content for rc in chunks)):
        result.text = re.sub(r'\b([A-Z][A-Z0-9-]{1,11})\s*\(([A-Za-z][A-Za-z /&-]{3,100})\)',
                             lambda m: m.group(1) if unsupported_expansions(m.group(0), '\n'.join(rc.chunk.content for rc in chunks)) else m.group(0), result.text)
    evidence_sufficient = INSUFFICIENT_EVIDENCE_MSG.lower() not in result.text.lower()
    if require_citations:
        indices = [int(i) for i in _CITATION_RE.findall(result.text)]
        evidence_sufficient = evidence_sufficient and bool(indices) and all(1 <= i <= len(chunks) for i in indices)
        if not evidence_sufficient:
            result.text = INSUFFICIENT_EVIDENCE_MSG
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
