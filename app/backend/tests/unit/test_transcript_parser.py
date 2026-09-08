from meeting_intel.ingestion.transcript_parser import parse_vtt

VTT = """WEBVTT

00:00:00.000 --> 00:00:05.230
<v Chetan Kumar>We should confirm the CrewAI requirement first.</v>

00:31:42.000 --> 00:32:17.500
<v Ravi Shah>I think the existing architecture is sufficient.</v>
"""


def test_parse_vtt_extracts_speaker_and_timestamps():
    cues = parse_vtt(VTT)
    assert len(cues) == 2

    first = cues[0]
    assert first.speaker == "Chetan Kumar"
    assert first.text == "We should confirm the CrewAI requirement first."
    assert first.start_seconds == 0.0
    assert first.end_seconds == 5.23

    second = cues[1]
    assert second.speaker == "Ravi Shah"
    assert second.start_seconds == 31 * 60 + 42
    assert second.end_seconds == 32 * 60 + 17.5


def test_parse_vtt_ignores_cues_without_text():
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n\n"
    assert parse_vtt(vtt) == []


def test_parse_vtt_handles_missing_voice_tag():
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello without a speaker tag\n"
    cues = parse_vtt(vtt)
    assert len(cues) == 1
    assert cues[0].speaker is None
    assert cues[0].text == "Hello without a speaker tag"
