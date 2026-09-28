"""Answer directly from scoped uploaded evidence without inventing approval metadata."""
from collections import defaultdict
from datetime import date
from dataclasses import replace
import re

from meeting_intel.agents.answer_agent import AnswerResult, answer_from_evidence, _to_citation
from meeting_intel.retrieval.hybrid_search import RetrievedChunk, get_search_provider
from meeting_intel.retrieval.restore_imports import restore_imports


def fallback(customer, question):
    contact = customer.sme or f'the {customer.name} account SME or account manager'
    return AnswerResult(text=f"I couldn't find the requested information in the uploaded {customer.name} documents. "
                             f"Please contact {contact}.", evidence_sufficient=False, retrieval_query=question)


def daily_checklist(chunks, *, customer, today: date, role=None):
    """Use explicit schedule headings. Unspecified weekly/monthly dates are not due today."""
    due = []
    uncertain_schedule = False
    for rc in chunks:
        heading = (rc.chunk.section or '').strip().casefold()
        if re.fullmatch(r'daily(?:\s*/\s*as needed)?', heading):
            due.append(rc)
        elif heading == today.strftime('%A').casefold():
            due.append(rc)
        elif re.fullmatch(r'(weekly|bi-weekly|monthly|quarterly)(?:\s*/.*)?', heading):
            uncertain_schedule = True
    if not due:
        return None
    # Different documents may represent different roles/versions: do not merge them.
    if len({rc.chunk.id.rsplit(':', 1)[0] for rc in due}) != 1:
        return None
    lines = []
    for i, rc in enumerate(due, 1):
        for paragraph in re.split(r'\n\s*\n', rc.chunk.content):
            if paragraph.strip():
                lines.append(f'{len(lines) + 1}. {paragraph.strip()} [S{i}]')
    text = f"Documented {customer.name} daily/as-needed checklist ({today.isoformat()}, {today:%A}):\n\n" + '\n'.join(lines)
    if role is None:
        text += '\n\nThese are the duties described in the uploaded document; your personal role and access are not confirmed.'
    if uncertain_schedule:
        text += '\nWeekly/monthly duties are also documented, but no exact due date is established for today.'
    text += '\nSource: ' + (due[0].chunk.source_file or 'Uploaded document')
    return AnswerResult(text=text, sources=[_to_citation(rc) for rc in due], retrieved_chunks=due,
                        model='document-schedule', evidence_sufficient=True)


def procedure_chunks(chunks, question):
    from meeting_intel.agents.answer_focus import focused_procedures
    return focused_procedures(chunks, question)


def documented_details(chunks, question):
    """Return supported source text when the model cannot establish a full procedure.

    This is explicitly a partial reference answer, not a synthesized SOP. Never
    manufacture connecting steps or suppress documented scope restrictions.
    """
    selected = []
    seen = set()
    for rc in chunks:
        document_id = rc.chunk.id.rsplit(':', 1)[0]
        if document_id in seen:
            continue
        paragraphs = re.split(r'\n\s*\n', rc.chunk.content)
        matches = [i for i, paragraph in enumerate(paragraphs)
                   if procedure_chunks([replace(rc, chunk=replace(rc.chunk, content=paragraph, section=None))], question)]
        if not matches:
            continue
        start = matches[0]
        end = min(len(paragraphs), start + 9)
        for index in range(start + 1, end):
            if re.match(r'^\d+\.\s+[A-Z]', paragraphs[index]):
                end = index
                break
        excerpt = '\n\n'.join(rc.chunk.content for rc in procedure_chunks([rc], question)).strip()
        if not excerpt:
            continue
        selected.append(replace(rc, chunk=replace(rc.chunk, content=excerpt)))
        seen.add(document_id)
        if len(selected) == 3:
            break
    if not selected:
        return None
    text = ('The meeting documents do not provide a complete end-to-end procedure. '
            'The following are documented excerpts, not a verified sequence of steps:\n\n')
    text += '\n\n'.join(f'{rc.chunk.content} [S{i}]' for i, rc in enumerate(selected, 1))
    return AnswerResult(text=text, sources=[_to_citation(rc) for rc in selected], retrieved_chunks=selected,
                        retrieval_query=question, model='documented-reference-excerpts', evidence_sufficient=True)


async def answer_uploaded(db, *, meeting, user, customer, question, intent, today, document=None):
    document_ids = customer.uploaded_sources.get(intent, [])
    if document is not None:
        document_ids = [d for d in document_ids if d == f'hist:{document.file_hash[:16]}']
    if not document_ids:
        return fallback(customer, question)
    # Restore only the explicitly customer-bound source documents for this route.
    for document_id in document_ids:
        await restore_imports(db, tenant_id=user.tenant_id, meeting_ids=[meeting.id], document_id=document_id,
                              customer_id=customer.id)
    hits = await get_search_provider().chunks_for_meeting(
        tenant_id=user.tenant_id, meeting_id=meeting.id, customer_id=customer.id, document_ids=document_ids)
    chunks = [RetrievedChunk(chunk=h, score=h.score, vector_rank=h.vector_rank, keyword_rank=h.keyword_rank) for h in hits]
    if intent == 'DAILY_TASKS':
        return daily_checklist(chunks, customer=customer, today=today, role=customer.roles.get(user.id)) or fallback(customer, question)
    if intent == 'PROCEDURE':
        chunks = procedure_chunks(chunks, question)
    else:
        # Account lookup uses the existing ranked retriever, constrained to the source list.
        from meeting_intel.retrieval.hybrid_search import hybrid_search
        chunks = []
        for document_id in document_ids:
            chunks.extend(await hybrid_search(db, tenant_id=user.tenant_id, meeting_ids=[meeting.id],
                query=question, customer_id=customer.id, document_id=document_id, top_k=4))
    if not chunks:
        return fallback(customer, question)
    result = await answer_from_evidence(chunks=chunks, history=[], question=question, require_citations=True,
        instructions=(f'Answer this {customer.name} operational question directly from the uploaded documents. '
                      'These are reference documents; approval/current version is not established. Do not claim otherwise. '
                      'Give one consolidated answer about the requested topic. You may summarize directly supported '
                      'details across these same-customer references, citing each claim. Multiple sources alone are not a conflict. '
                      'If there is no complete SOP, say so and provide the documented details as a partial overview, '
                      'not an invented sequence of steps. Do not refuse all information merely because some steps are absent. '
                      'Number steps only if the evidence explicitly establishes order or dependency; source fact order '
                      'does not establish workflow order. Describe historical activities as "historically involved". '
                      'Separate documented procedure, historical information, current ownership, and related context. '
                      'Never turn Work-at-Risk instructions or another adjacent process into change-order steps. '
                      'When sources actually disagree, describe the disagreement and abstain on that disputed instruction. '
                      'Never fill missing steps with general knowledge. '
                      'If the document says the user does not own this process, explain that limitation with a citation. '
                      'Preserve all conditions on access, ownership and applicability. If no directly relevant facts exist, abstain.'))
    if result.evidence_sufficient:
        return result
    if intent == 'PROCEDURE':
        return documented_details(chunks, question) or fallback(customer, question)
    return fallback(customer, question)
