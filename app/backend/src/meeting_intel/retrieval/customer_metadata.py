"""Apply explicit, deployment-managed document/customer bindings at indexing."""
import json
from dataclasses import replace
from pathlib import Path

from meeting_intel.config import get_settings


# Rebuilt from persisted import metadata for each authorized workspace request.
_inferred_bindings = {}


def set_folder_bindings(tenant_id, meeting_id, bindings):
    _inferred_bindings[(tenant_id, meeting_id)] = bindings


def all_bindings(data):
    explicit = data.get('document_bindings', [])
    keys = {(b['tenant_id'], b['meeting_id'], b['document_id']) for b in explicit}
    return explicit + [b for group in _inferred_bindings.values() for b in group
                       if (b['tenant_id'], b['meeting_id'], b['document_id']) not in keys]


def customer_document_ids(*, tenant_id, meeting_ids, customer_id):
    data = json.loads(Path(get_settings().operational_catalog_path).read_text(encoding='utf-8'))
    return {b['document_id'] for b in all_bindings(data)
            if b['tenant_id'] == tenant_id and b['meeting_id'] in meeting_ids and b['customer_id'] == customer_id}


def bind_customers(chunks):
    settings = get_settings()
    if not settings.operational_enabled:
        return chunks
    data = json.loads(Path(settings.operational_catalog_path).read_text(encoding='utf-8'))
    bindings = all_bindings(data)
    result = []
    for chunk in chunks:
        matches = {b['customer_id'] for b in bindings if b['tenant_id'] == chunk.tenant_id
                   and b['meeting_id'] == chunk.meeting_id and b['document_id'] == chunk.document_id}
        if len(matches) > 1 or matches and chunk.customer_id and chunk.customer_id not in matches:
            raise ValueError('Conflicting customer document bindings')
        result.append(replace(chunk, customer_id=next(iter(matches))) if matches else chunk)
    return result
