"""Unit tests for the untrusted-file-handling helpers used by the historical
import API (§30 of the upgrade spec): path traversal, absolute paths, null
bytes, and filename sanitization."""
import pytest

from meeting_intel.security.file_safety import (
    UnsafePathError,
    file_hash,
    sanitize_filename,
    sanitize_relative_path,
)


def test_sanitize_filename_strips_directories():
    assert sanitize_filename("Project_A/Meeting_01.vtt") == "Meeting_01.vtt"
    assert sanitize_filename("..\\..\\evil.txt") == "evil.txt"


def test_sanitize_filename_rejects_empty_result():
    with pytest.raises(UnsafePathError):
        sanitize_filename("")
    with pytest.raises(UnsafePathError):
        sanitize_filename("..")


def test_sanitize_relative_path_preserves_folder_structure():
    assert sanitize_relative_path("Project_A/Meeting_01.vtt") == "Project_A/Meeting_01.vtt"


def test_sanitize_relative_path_rejects_traversal():
    with pytest.raises(UnsafePathError):
        sanitize_relative_path("../../etc/passwd")
    with pytest.raises(UnsafePathError):
        sanitize_relative_path("Project_A/../../../etc/passwd")


def test_sanitize_relative_path_rejects_absolute_paths():
    with pytest.raises(UnsafePathError):
        sanitize_relative_path("/etc/passwd")
    with pytest.raises(UnsafePathError):
        sanitize_relative_path("C:\\Windows\\System32\\evil.dll")


def test_sanitize_relative_path_rejects_null_byte():
    with pytest.raises(UnsafePathError):
        sanitize_relative_path("Project_A/file.txt\x00.vtt")


def test_file_hash_is_stable_and_content_dependent():
    a = file_hash(b"hello world")
    b = file_hash(b"hello world")
    c = file_hash(b"hello world!")
    assert a == b
    assert a != c
    assert len(a) == 64
