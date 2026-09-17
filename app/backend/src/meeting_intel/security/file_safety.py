"""Untrusted-file handling for the historical import pipeline (§30 of the
upgrade spec). Every file arriving through `POST /api/historical-imports` is
treated as attacker-controlled: its name, its declared relative path, and
its bytes.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB per file
MAX_FILES_PER_IMPORT = 2000
MAX_TOTAL_IMPORT_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB per batch

_UNSAFE_CHARS = re.compile(r'[\x00-\x1f<>:"|?*\\]')


class UnsafePathError(ValueError):
    """Raised when a filename/relative path cannot be made safe."""


def sanitize_filename(name: str) -> str:
    """Strips directory components and dangerous characters. Never returns
    something that could be interpreted as a path outside the target
    directory."""
    name = unicodedata.normalize("NFKC", name).strip()
    # Take only the final path segment regardless of which slash style the
    # browser sent (webkitdirectory relativePath is always forward-slash,
    # but never trust that from a raw multipart field).
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE_CHARS.sub("_", name).lstrip(". ")
    if not name or name in {".", ".."}:
        raise UnsafePathError("Filename is empty or unsafe after sanitization.")
    return name[:255]


def sanitize_relative_path(path: str) -> str:
    """Normalizes a client-supplied relative path (e.g. from
    `webkitRelativePath`), rejecting path traversal (`..`), absolute paths,
    and null bytes, while preserving the folder structure for meeting
    association and the import report."""
    if "\x00" in path:
        raise UnsafePathError("Path contains a null byte.")
    path = unicodedata.normalize("NFKC", path).strip().replace("\\", "/")
    if path.startswith("/") or (len(path) > 1 and path[1] == ":"):
        raise UnsafePathError("Absolute paths are not allowed.")
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise UnsafePathError("Path traversal ('..') is not allowed.")
    cleaned = [_UNSAFE_CHARS.sub("_", p)[:255] for p in parts]
    if not cleaned:
        raise UnsafePathError("Path is empty after sanitization.")
    return "/".join(cleaned)


def file_hash(content: bytes) -> str:
    """Stable SHA-256 identity used for duplicate detection (§17) — the same
    bytes always hash to the same value, independent of filename/path."""
    return hashlib.sha256(content).hexdigest()
