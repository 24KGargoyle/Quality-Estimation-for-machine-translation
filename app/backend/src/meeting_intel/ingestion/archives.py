"""Bounded, in-memory archive expansion. Never extract uploaded paths to disk."""
import io
from pathlib import PurePosixPath
import stat
import zipfile

from meeting_intel.security.file_safety import sanitize_relative_path, sanitize_filename, MAX_FILES_PER_IMPORT

MAX_EXPANDED_BYTES = 250 * 1024 * 1024


def expand_zip(content, relative_path):
    from meeting_intel.ingestion.historical_import import StagedFile
    output = []
    total = 0
    paths = set()

    def visit(data, parent, depth):
        nonlocal total
        if depth > 3:
            raise ValueError('Archive nesting exceeds three levels.')
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if len(archive.infolist()) > MAX_FILES_PER_IMPORT:
                raise ValueError('Archive contains too many entries.')
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                    raise ValueError('Archive contains a symbolic link or encrypted entry.')
                name = sanitize_relative_path(info.filename)
                path = sanitize_relative_path(parent + '/' + name)
                if path in paths:
                    raise ValueError('Archive has duplicate normalized paths.')
                paths.add(path)
                if len(paths) > MAX_FILES_PER_IMPORT or total + info.file_size > MAX_EXPANDED_BYTES:
                    raise ValueError('Archive exceeds the expanded file count or 250 MB limit.')
                if info.file_size > max(1, info.compress_size) * 200:
                    raise ValueError('Archive compression ratio exceeds the safety limit.')
                with archive.open(info) as stream:
                    body = stream.read(min(info.file_size, MAX_EXPANDED_BYTES - total) + 1)
                total += len(body)
                if total > MAX_EXPANDED_BYTES or len(body) != info.file_size:
                    raise ValueError('Archive expanded size is invalid.')
                if name.lower().endswith('.zip'):
                    visit(body, str(PurePosixPath(path).with_suffix('')), depth + 1)
                else:
                    output.append(StagedFile(filename=sanitize_filename(name), relative_path=path, content=body))

    try:
        visit(content, str(PurePosixPath(relative_path).with_suffix('')), 1)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError('Archive is corrupt, encrypted, or uses unsupported compression.') from exc
    if not output:
        raise ValueError('Archive contains no files.')
    return output
