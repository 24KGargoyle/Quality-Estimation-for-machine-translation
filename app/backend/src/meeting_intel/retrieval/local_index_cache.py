"""Local derived index cache; loaded only after source/tenant authorization."""
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from meeting_intel.config import get_settings
from meeting_intel.retrieval.search_provider import IndexableChunk


def cache_path(tenant_id, meeting_id, document_id):
    key = hashlib.sha256(f'{tenant_id}:{meeting_id}:{document_id}'.encode()).hexdigest()
    return Path(get_settings().local_blob_storage_dir) / '.index-cache' / (key + '.json')


def save(chunks):
    if not chunks or get_settings().file_storage != 'local':
        return
    c = chunks[0]
    path = cache_path(c.tenant_id, c.meeting_id, c.document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    import uuid
    temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps([asdict(c) for c in chunks]), encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load(tenant_id, meeting_id, document_id):
    try:
        chunks = [IndexableChunk(**c) for c in json.loads(cache_path(tenant_id,meeting_id,document_id).read_text(encoding='utf-8'))]
        if all((c.tenant_id,c.meeting_id,c.document_id)==(tenant_id,meeting_id,document_id) for c in chunks):
            return chunks
    except (OSError, ValueError, TypeError):
        pass
    return []
