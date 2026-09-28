from datetime import date

import pytest

from meeting_intel.operational import Customer
from meeting_intel.retrieval.hybrid_search import RetrievedChunk
from meeting_intel.retrieval.search_provider import SearchHit
from meeting_intel.uploaded_operational import daily_checklist, procedure_chunks, documented_details


def chunk(text, section='Document', id='hist:bp:0', filename='BP Playbook.docx'):
    hit = SearchHit(id=id, meeting_id='m', customer_id='bp', content=text, section=section,
                    chunk_index=0, start_time=0, end_time=0, source_file=filename, file_type='docx')
    return RetrievedChunk(chunk=hit, score=1, vector_rank=None, keyword_rank=None)


def test_uploaded_daily_sections_preserve_conditions_without_inventing_due_dates():
    customer = Customer(id='bp', name='BP', tenant_id='t')
    evidence = [chunk('Review account email.\n\nUpdate trackers when a resource changes.', 'Daily / As Needed'),
                chunk('Approve timesheets once access is complete.', 'Weekly', id='hist:bp:1'),
                chunk('Send reports.', 'Monthly', id='hist:bp:2')]
    result = daily_checklist(evidence, customer=customer, today=date(2026, 9, 24))
    assert 'Thursday' in result.text
    assert 'when a resource changes' in result.text
    assert 'Approve timesheets' not in result.text
    assert 'no exact due date' in result.text
    assert 'personal role and access are not confirmed' in result.text
    assert len(result.sources) == 1 and '[S1]' in result.text


def test_no_vendor_procedure_from_fieldglass_mentions():
    evidence = [chunk('Fieldglass access will transition later. Change orders are not currently owned.')]
    assert procedure_chunks(evidence, 'How do I create a Fieldglass vendor?') == []


def test_procedure_multiple_references_reach_grounding_for_conflict_assessment():
    evidence = [chunk('Create a change order using the form.', 'Change Order'),
                chunk('Create a change order in another system.', 'Change Order', id='hist:other:0')]
    assert len(procedure_chunks(evidence, 'How do I create a change order?')) == 2


def test_conversational_question_and_change_note_alias():
    evidence = [chunk('Request pricing sheets and prepare the Change Note.', 'Responsibilities')]
    assert procedure_chunks(evidence, 'Can you check anything mentioned How do I create a change order?') == evidence


def test_partial_procedure_returns_actual_requirements_not_a_blanket_refusal():
    evidence = [chunk('Unrelated cadence.\n\n10. IRU Change Order Requests\n\nWhen requesting support, include:\n\nProject number\n\nProposed end date\n\n11. Travel\n\nBook a flight.', 'Document')]
    result = documented_details(evidence, 'How do I create a change order?')
    assert result.evidence_sufficient
    assert 'Project number' in result.text and 'Proposed end date' in result.text
    assert 'Unrelated cadence' not in result.text and 'Book a flight' not in result.text
    assert 'not a verified sequence' in result.text and result.sources


@pytest.mark.asyncio
async def test_upload_answers_require_valid_citations(monkeypatch):
    from meeting_intel.agents import answer_agent
    from meeting_intel.llm.client import LLMResult
    class Model:
        async def complete(self, **kwargs):
            return LLMResult('Invented steps without citations', 1, 'test')
    monkeypatch.setattr(answer_agent, 'get_llm_provider', lambda: Model())
    result = await answer_agent.answer_from_evidence(chunks=[chunk('Documented fact')], history=[],
        question='Who is the account manager?', require_citations=True)
    assert not result.evidence_sufficient and not result.sources


@pytest.mark.asyncio
async def test_customer_and_document_filters_are_intersected():
    from meeting_intel.retrieval.memory_search import InMemorySearchProvider
    from meeting_intel.retrieval.search_provider import IndexableChunk
    provider = InMemorySearchProvider()
    await provider.index_chunks([IndexableChunk(id=str(i), tenant_id='t', meeting_id='m', meeting_title='M',
        customer_id=customer, document_id=doc, content='evidence', chunk_index=i, start_time=0, end_time=0)
        for i, (customer, doc) in enumerate([('bp', 'wanted'), ('bp', 'unrelated'), ('chevron', 'wanted')])])
    hits = await provider.chunks_for_meeting(tenant_id='t', meeting_id='m', customer_id='bp', document_ids=['wanted'])
    assert [h.id for h in hits] == ['0']
