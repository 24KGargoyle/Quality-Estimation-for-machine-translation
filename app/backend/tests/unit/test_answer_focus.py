import pytest
from types import SimpleNamespace
from dataclasses import dataclass
from meeting_intel.agents.answer_focus import answer_intent, answer_rules, focused_procedures, retrieval_question
from meeting_intel.retrieval.hybrid_search import RetrievedChunk
from meeting_intel.retrieval.search_provider import SearchHit

@pytest.mark.parametrize('question,intent', [
 ('How to do Project Accounting?', 'procedure'),
 ('creating change order process?', 'procedure'),
 ('What are my tasks?', 'responsibility'),
 ('What is pending?', 'pending'),
 ('Who owns contract renewal?', 'ownership'),
 ('When is the report due?', 'timing'),
])
def test_answer_intent_and_rules(question,intent):
    assert answer_intent(question) == intent
    assert 'Cite each important claim' in answer_rules(question)
    assert retrieval_question(question).startswith(question)

def chunk(text, section=None):
    return RetrievedChunk(chunk=SearchHit(id='doc:1',meeting_id='m',content=text,chunk_index=0,start_time=0,end_time=0,section=section),score=1,vector_rank=None,keyword_rank=None)

def test_procedure_excludes_related_duties_and_preserves_citation_identity():
    related=chunk('Project Accounting responsibilities include general communication and consultant check-ins.')
    direct=chunk('For Project Accounting discrepancies, submit an issue ticket.\n\nConsultant check-ins happen weekly.')
    assert focused_procedures([related], 'How to do Project Accounting?') == []
    result=focused_procedures([direct], 'How to do Project Accounting?')
    assert len(result)==1
    assert result[0].chunk.id == direct.chunk.id
    assert 'submit an issue ticket' in result[0].chunk.content
    assert 'check-ins' not in result[0].chunk.content
    assert 'complete end-to-end procedure' in answer_rules('How to submit expenses?')

def test_no_process_from_keyword_overlap():
    assert focused_procedures([chunk('Project Accounting is discussed alongside timesheets and reporting.')], 'How to do Project Accounting?') == []


def test_historical_facts_remain_historical_and_prompt_requires_explicit_sequence():
    evidence = chunk('Historically, the change order process involved requesting pricing sheets and creating resource orders.')
    selected = focused_procedures([evidence], 'creating change order process?')
    assert selected[0].chunk.content == evidence.chunk.content
    rules = answer_rules('creating change order process?')
    assert 'Use numbered steps only when retrieved evidence explicitly establishes' in rules
    assert 'Never infer a workflow sequence from the order of facts' in rules
    assert 'historically involved' in rules
    assert 'current responsibilities/ownership' in rules
    assert 'unnumbered bullets' in rules
