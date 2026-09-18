"""Unit tests for the Related Intelligence sidebar (§2/§3 of the Search
Intelligence upgrade). §18 test cases: related topics/documents/people,
web research trigger, and no-unnecessary-web-search."""
import pytest

from meeting_intel.agents.intelligence_panel import build_intelligence_panel
from meeting_intel.retrieval.hybrid_search import RetrievedChunk, get_search_provider
from meeting_intel.retrieval.search_provider import IndexableChunk, SearchHit
from meeting_intel.web_research.provider import extract_research_topic, should_research_web


def _rc(speaker, content, document_type="transcript", source_file=None, score=1.0):
    hit = SearchHit(
        id=f"c-{content[:8]}", meeting_id="m1", content=content, chunk_index=0, start_time=0, end_time=1,
        speaker_name=speaker, document_type=document_type, source_file=source_file, score=score,
    )
    return RetrievedChunk(chunk=hit, score=score, vector_rank=1, keyword_rank=1)


# --- Related topics ---

@pytest.mark.asyncio
async def test_related_topics_extracted_from_retrieved_evidence_only():
    chunks = [
        _rc("Alice", "We should move the API layer to Azure AI Search for better security."),
        _rc("Bob", "Azure Security is a key requirement for the deployment."),
    ]
    panel = await build_intelligence_panel(
        tenant_id="t1", meeting_id="m1", question="What did the team decide about the architecture?",
        chunks=chunks, participant_names=["Alice", "Bob"], mentioned_people=[], cited_source_files=set(),
    )
    assert "Azure" in panel.related_topics
    assert "Security" in panel.related_topics
    # Never invents a topic absent from the evidence text.
    assert "Kubernetes" not in panel.related_topics


@pytest.mark.asyncio
async def test_related_topics_empty_when_no_chunks():
    panel = await build_intelligence_panel(
        tenant_id="t1", meeting_id="m1", question="Hello", chunks=[], participant_names=[],
        mentioned_people=[], cited_source_files=set(),
    )
    assert panel.related_topics == []


# --- Related documents ---

@pytest.mark.asyncio
async def test_related_documents_lists_other_files_in_the_meeting():
    provider = get_search_provider()
    await provider.index_chunks([
        IndexableChunk(
            id="d1:0", tenant_id="t1", meeting_id="m1", meeting_title="M", content="Action items here",
            chunk_index=0, start_time=0, end_time=0, document_id="d1", source_file="Action_Items.xlsx",
            file_type="xlsx", document_type="spreadsheet", sheet_name="Actions",
        ),
    ])
    chunks = [_rc("Alice", "We discussed action items.", source_file="Meeting.vtt")]
    panel = await build_intelligence_panel(
        tenant_id="t1", meeting_id="m1", question="What did we discuss?", chunks=chunks,
        participant_names=["Alice"], mentioned_people=[], cited_source_files={"Meeting.vtt"},
    )
    assert any(d.source_file == "Action_Items.xlsx" for d in panel.related_documents)
    assert all(d.source_file != "Meeting.vtt" for d in panel.related_documents)  # excluded: already cited


@pytest.mark.asyncio
async def test_related_documents_empty_when_meeting_has_no_other_files():
    panel = await build_intelligence_panel(
        tenant_id="t1", meeting_id="m-empty", question="Anything?", chunks=[], participant_names=[],
        mentioned_people=[], cited_source_files=set(),
    )
    assert panel.related_documents == []


# --- Related people ---

@pytest.mark.asyncio
async def test_related_people_includes_participants_speakers_and_mentions():
    chunks = [_rc("Bob", "Bob agreed to the plan.")]
    panel = await build_intelligence_panel(
        tenant_id="t1", meeting_id="m1", question="What did Alice and Bob agree on?", chunks=chunks,
        participant_names=["Chelsea Potter"], mentioned_people=["Alice"], cited_source_files=set(),
    )
    assert "Alice" not in panel.related_people
    assert "Chelsea Potter" not in panel.related_people
    assert "Bob" in panel.related_people


# --- Web research trigger ---

@pytest.mark.asyncio
async def test_web_research_triggered_for_best_practice_question():
    assert should_research_web("Search the web for best practices for this architecture?") is True


@pytest.mark.asyncio
async def test_web_research_not_triggered_for_person_question():
    assert should_research_web("What did Alice say about deployment?") is False


@pytest.mark.asyncio
async def test_web_research_not_triggered_for_plain_topic_recap():
    assert should_research_web("What was discussed in the meeting?") is False


@pytest.mark.asyncio
async def test_panel_includes_web_research_only_when_triggered():
    panel_yes = await build_intelligence_panel(
        tenant_id="t1", meeting_id="m1", question="Search the web for best practices for this approach?",
        chunks=[], participant_names=[], mentioned_people=[], cited_source_files=set(),
    )
    assert panel_yes.web_research is not None
    assert panel_yes.web_research.configured is False  # no Bing key in this environment

    panel_no = await build_intelligence_panel(
        tenant_id="t1", meeting_id="m1", question="What did Alice say?",
        chunks=[], participant_names=[], mentioned_people=[], cited_source_files=set(),
    )
    assert panel_no.web_research is None


def test_extract_research_topic_strips_question_scaffolding():
    topic = extract_research_topic("What are the best practices for this architecture discussed in this meeting?")
    assert "best practices" in topic
    assert "architecture" in topic


@pytest.mark.asyncio
async def test_external_research_uses_only_public_topic_and_real_links(monkeypatch):
    import httpx
    from meeting_intel.config import get_settings
    from meeting_intel.web_research.provider import AzureWebResearchProvider
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_endpoint", "https://example.openai.azure.com")
    monkeypatch.setattr(settings, "azure_openai_api_key", "test")
    monkeypatch.setattr(settings, "web_research_deployment", "test-web")
    async def post(self, url, **kwargs):
        assert kwargs["json"]["input"] == "Azure Search best practices"
        assert kwargs["json"]["store"] is False
        return httpx.Response(200, request=httpx.Request("POST", url), json={"output": [{"content": [{"annotations": [
            {"type": "url_citation", "url": "https://learn.microsoft.com/search", "title": "Official docs"},
            {"type": "url_citation", "url": "javascript:alert(1)", "title": "Invalid"}
        ]}]}]})
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    result = await AzureWebResearchProvider().research("Azure Search best practices")
    assert [r.url for r in result.results] == ["https://learn.microsoft.com/search"]


def test_web_requires_explicit_external_request():
    assert not should_research_web("Compare this meeting with previous meetings")
    assert not should_research_web("What are best practices for Azure Search?")
    assert not should_research_web("Search the web for what did Alice say about best practices")
