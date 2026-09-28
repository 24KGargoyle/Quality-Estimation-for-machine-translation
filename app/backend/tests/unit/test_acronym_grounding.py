import pytest
from meeting_intel.agents.acronym_grounding import requested_acronym, unsupported_expansions
from meeting_intel.agents.answer_agent import answer_from_evidence
from meeting_intel.retrieval.hybrid_search import RetrievedChunk
from meeting_intel.retrieval.search_provider import SearchHit

@pytest.mark.parametrize('q', ['what is CMPM', 'wht is CMPM', 'what does CMPM stand for?'])
def test_definition_intent(q):
    assert requested_acronym(q) == 'CMPM'

def test_expansion_requires_explicit_source_definition():
    assert unsupported_expansions('CMPM (Contractor Management Process Model)', 'CMPM time reporting')
    assert not unsupported_expansions('ABC (Account Billing Control)', 'Account Billing Control (ABC)')

@pytest.mark.asyncio
@pytest.mark.parametrize('content,expected', [('CMPM time reporting hours are preliminary.', 'do not define'),
 ('CMPM stands for Customer Monthly Payment Management.', 'Customer Monthly Payment Management')])
async def test_definition_answer_without_model(content, expected):
    chunk=RetrievedChunk(chunk=SearchHit(id='doc:1',meeting_id='m',content=content,chunk_index=0,start_time=0,end_time=0),score=1,vector_rank=None,keyword_rank=None)
    result=await answer_from_evidence(chunks=[chunk],question='what is CMPM',history=[
        {'role':'assistant','content':'CMPM (Contractor Management Process Model)'}])
    assert expected in result.text
    assert 'should not be relied on' in result.text
    assert result.sources and result.model == 'source-definition'
