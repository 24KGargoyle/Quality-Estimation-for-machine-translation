"""Unit tests for query understanding (§1 of the Search Intelligence
upgrade): person detection, intent classification, and the deterministic
reranking pass. §18 test cases: generic/person/topic/document question
intent classification."""
from meeting_intel.agents.query_understanding import find_mentioned_names, understand_query
from meeting_intel.retrieval.rerank import rerank
from meeting_intel.retrieval.search_provider import SearchHit

PARTICIPANTS = ["Alice Smith", "Bob Jones", "Chelsea Potter"]


def test_person_question_detects_speaker_and_person_intent():
    u = understand_query("What did Alice say about the project?", PARTICIPANTS)
    assert u.person == "Alice Smith"
    assert u.intent == "person"
    assert u.is_cross_meeting is False


def test_generic_question_has_no_person_and_generic_or_topic_intent():
    u = understand_query("Hello", PARTICIPANTS)
    assert u.person is None
    assert u.intent == "generic"


def test_topic_question_without_a_person_is_topic_intent():
    u = understand_query("What was decided about the deployment pipeline?", PARTICIPANTS)
    assert u.person is None
    assert u.intent == "topic"


def test_document_question_detects_document_intent():
    u = understand_query("What does the architecture document say?", PARTICIPANTS)
    assert u.intent == "document"


def test_find_mentioned_names_returns_all_matches_in_order():
    names = find_mentioned_names("Did Alice agree with Bob's plan?", PARTICIPANTS)
    assert names == ["Alice Smith", "Bob Jones"]


def test_find_mentioned_names_empty_when_no_match():
    assert find_mentioned_names("What was discussed overall?", PARTICIPANTS) == []


def _hit(id_, speaker, content, score=0.5):
    return SearchHit(id=id_, meeting_id="m1", content=content, chunk_index=0, start_time=0, end_time=1, speaker_name=speaker, score=score)


def test_rerank_boosts_matching_speaker_to_top():
    hits = [
        _hit("c1", "Bob Jones", "We should launch the pilot next week.", score=0.9),
        _hit("c2", "Alice Smith", "I agree with the plan.", score=0.1),
    ]
    ranked = rerank(hits, query="What did Alice say?", speaker="Alice Smith")
    assert ranked[0].id == "c2"


def test_rerank_boosts_exact_keyword_matches():
    hits = [
        _hit("c1", "Bob", "totally unrelated content", score=0.5),
        _hit("c2", "Alice", "we should launch the pilot next week", score=0.5),
    ]
    ranked = rerank(hits, query="launch pilot", speaker=None)
    assert ranked[0].id == "c2"


def test_rerank_with_no_hits_returns_empty():
    assert rerank([], query="anything", speaker=None) == []


def test_live_network_is_blocked():
    import socket
    import pytest
    with socket.socket() as sock:
        with pytest.raises(AssertionError, match="Live network"):
            sock.connect(("203.0.113.1", 443))
