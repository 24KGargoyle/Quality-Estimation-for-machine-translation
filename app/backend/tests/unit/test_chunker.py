from meeting_intel.ingestion.chunker import chunk_cues
from meeting_intel.ingestion.transcript_parser import TranscriptCue


def test_merges_consecutive_same_speaker_cues():
    cues = [
        TranscriptCue(speaker="Chetan", start_seconds=0, end_seconds=5, text="Part one."),
        TranscriptCue(speaker="Chetan", start_seconds=5, end_seconds=10, text="Part two."),
    ]
    chunks = chunk_cues(cues)
    assert len(chunks) == 1
    assert chunks[0].text == "Part one. Part two."
    assert chunks[0].speaker == "Chetan"
    assert chunks[0].start_seconds == 0
    assert chunks[0].end_seconds == 10


def test_speaker_change_starts_new_chunk():
    cues = [
        TranscriptCue(speaker="Chetan", start_seconds=0, end_seconds=5, text="Hello."),
        TranscriptCue(speaker="Ravi", start_seconds=5, end_seconds=10, text="Hi there."),
    ]
    chunks = chunk_cues(cues)
    assert len(chunks) == 2
    assert chunks[0].speaker == "Chetan"
    assert chunks[1].speaker == "Ravi"


def test_max_chars_splits_long_same_speaker_run():
    cues = [TranscriptCue(speaker="Chetan", start_seconds=i, end_seconds=i + 1, text="x" * 500) for i in range(3)]
    chunks = chunk_cues(cues, max_chars=900)
    assert len(chunks) > 1
    assert all(c.speaker == "Chetan" for c in chunks)


def test_no_metadata_lost_across_chunks():
    cues = [
        TranscriptCue(speaker="Chetan", start_seconds=0, end_seconds=5, text="A"),
        TranscriptCue(speaker="Ravi", start_seconds=5, end_seconds=9, text="B"),
        TranscriptCue(speaker="Chetan", start_seconds=9, end_seconds=12, text="C"),
    ]
    chunks = chunk_cues(cues)
    assert [c.speaker for c in chunks] == ["Chetan", "Ravi", "Chetan"]
    assert [c.text for c in chunks] == ["A", "B", "C"]
    total_chars = sum(len(c.text) for c in chunks)
    assert total_chars == sum(len(c.text) for c in cues)
