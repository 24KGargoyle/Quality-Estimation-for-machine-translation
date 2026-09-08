from meeting_intel.agents.meeting_router import extract_speaker_filter, is_cross_meeting_query


def test_default_is_single_meeting_scope():
    assert is_cross_meeting_query("What did Chetan say about CrewAI?") is False


def test_explicit_cross_meeting_phrases_detected():
    assert is_cross_meeting_query("Compare this with last week's meeting.") is True
    assert is_cross_meeting_query("What did we discuss across meetings about CrewAI?") is True
    assert is_cross_meeting_query("What was the outcome of the previous meeting?") is True


def test_extract_speaker_filter_matches_participant():
    participants = ["Chetan Kumar", "Ravi Shah"]
    assert extract_speaker_filter("What did Chetan say about CrewAI?", participants) == "Chetan Kumar"
    assert extract_speaker_filter("What did Ravi think?", participants) == "Ravi Shah"


def test_extract_speaker_filter_no_match_returns_none():
    participants = ["Chetan Kumar", "Ravi Shah"]
    assert extract_speaker_filter("What was decided overall?", participants) is None
