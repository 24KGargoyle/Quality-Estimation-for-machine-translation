"""Conservative folder-based customer resolution from persisted import metadata."""
import re
from pathlib import PurePosixPath
from sqlalchemy import select
from meeting_intel.db.models import HistoricalDocument
from meeting_intel.retrieval.customer_metadata import set_folder_bindings


def matches(text, names):
    text = text.replace('_', ' ')
    return any(re.search(r'(?<!\w)' + re.escape(name.replace('_', ' ')) + r'(?!\w)', text, re.I)
               for name in names if name)


async def folder_catalog(db, catalog, *, tenant_id, meeting_id):
    from meeting_intel.operational import Customer
    if db is None:
        return catalog
    catalog = catalog.model_copy(deep=True)
    customers = [c for c in catalog.customers if c.tenant_id == tenant_id]
    # Recognized account aliases; additional accounts use catalog names/aliases.
    for cid, name, aliases in [('bp', 'British Petroleum', ['BP']),
                               ('att', 'AT&T', ['AT&T', 'AT and T', 'AT T']),
                               ('chevron', 'Chevron', ['Chevron'])]:
        if not any(matches(name, [c.id, c.name, *c.aliases]) or any(a.casefold() in
                   [v.casefold() for v in [c.id, c.name, *c.aliases]] for a in aliases) for c in customers):
            customers.append(Customer(id=cid, name=name, tenant_id=tenant_id, aliases=aliases))
    documents = (await db.execute(select(HistoricalDocument).where(
        HistoricalDocument.tenant_id == tenant_id, HistoricalDocument.meeting_id == meeting_id,
    ))).scalars().all()
    assigned = []
    for doc in documents:
        folders = str(PurePosixPath(doc.relative_path.replace('\\', '/')).parent)
        found = [c for c in customers if matches(folders, [c.id, c.name, *c.aliases])]
        if len(found) != 1:
            continue
        customer = found[0]
        # A Chevron-named document inside a BP folder is not BP evidence.
        conflicts = [c for c in customers if c.id != customer.id and matches(doc.source_file, [c.id, c.name, *c.aliases])]
        if conflicts:
            continue
        assigned.append((doc, customer))
    bindings = []
    folder_ids = {c.id for _, c in assigned}
    # Mixed-account folders require explicit configuration/selection.
    if len(folder_ids) == 1:
        customer = assigned[0][1]
        configured = next((c for c in catalog.customers if c.tenant_id == tenant_id and c.id == customer.id), None)
        if configured is None:
            catalog.customers.append(customer)
        if meeting_id not in customer.meeting_ids:
            customer.meeting_ids.append(meeting_id)
        for doc, _ in assigned:
            document_id = f'hist:{doc.file_hash[:16]}'
            explicit = [b for b in catalog.document_bindings if b['tenant_id'] == tenant_id
                        and b['meeting_id'] == meeting_id and b['document_id'] == document_id]
            if explicit and any(b['customer_id'] != customer.id for b in explicit):
                continue
            bindings.append(dict(tenant_id=tenant_id, meeting_id=meeting_id,
                                 customer_id=customer.id, document_id=document_id))
            for intent in ('PROCEDURE', 'ACCOUNT_INFO', 'DAILY_TASKS'):
                sources = customer.uploaded_sources.setdefault(intent, [])
                if document_id not in sources:
                    sources.append(document_id)
    set_folder_bindings(tenant_id, meeting_id, bindings)
    return catalog
