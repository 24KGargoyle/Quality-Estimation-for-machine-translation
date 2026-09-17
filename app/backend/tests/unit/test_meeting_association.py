"""Unit tests for the pure (no-DB) meeting-association helpers: the
deterministic historical meeting id generator (§16 — "the same file must
produce the same logical ID if imported again") and the folder/filename
grouping key (§15)."""
from meeting_intel.ingestion.meeting_association import association_key, deterministic_historical_id


def test_deterministic_id_is_stable_for_the_same_tenant_and_key():
    a = deterministic_historical_id(tenant_id="t1", key="Project_A")
    b = deterministic_historical_id(tenant_id="t1", key="Project_A")
    assert a == b
    assert a.startswith("historical_")


def test_deterministic_id_differs_across_tenants():
    a = deterministic_historical_id(tenant_id="tenant-a", key="Project_A")
    b = deterministic_historical_id(tenant_id="tenant-b", key="Project_A")
    assert a != b


def test_deterministic_id_differs_across_keys():
    a = deterministic_historical_id(tenant_id="t1", key="Project_A")
    b = deterministic_historical_id(tenant_id="t1", key="Project_B")
    assert a != b


def test_association_key_groups_by_folder():
    key1, title1 = association_key(relative_path="Project_A/Meeting_01.vtt", filename="Meeting_01.vtt")
    key2, title2 = association_key(relative_path="Project_A/Architecture.docx", filename="Architecture.docx")
    assert key1 == key2  # same folder -> same meeting
    assert title1 == title2 == "Project A"


def test_association_key_falls_back_to_filename_stem_with_no_folder():
    key, title = association_key(relative_path="notes.txt", filename="notes.txt")
    assert key == "notes"
    assert title == "Notes"


def test_association_key_extracts_date_into_title():
    _, title = association_key(relative_path="Standup_2026-01-15/notes.txt", filename="notes.txt")
    assert "2026-01-15" in title
