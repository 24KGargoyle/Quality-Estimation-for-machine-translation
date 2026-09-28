from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from meeting_intel.folder_customer import folder_catalog
from meeting_intel.operational import Catalog, Customer, resolve_customer
from meeting_intel.retrieval.customer_metadata import _inferred_bindings

@pytest.mark.asyncio
@pytest.mark.parametrize('folder,cid', [('PMO/BP/BP US KT', 'bp'), ('PMO/Comms/AT&T/AT&T Legacy/archive', 'att')])
async def test_folder_customer_survives_reimport(folder, cid):
    docs = [SimpleNamespace(relative_path=folder+'/notes.docx', source_file='notes.docx', file_hash='a'*64)]
    db = AsyncMock()
    db.execute.return_value.scalars.return_value.all = lambda: docs
    # SQLAlchemy result accessors are synchronous.
    from unittest.mock import Mock
    db.execute.return_value = Mock()
    db.execute.return_value.scalars.return_value.all.return_value = docs
    catalog = await folder_catalog(db, Catalog(), tenant_id='tenant', meeting_id='new-meeting')
    customer, context = resolve_customer('about?', catalog.customers, meeting_id='new-meeting')
    assert customer.id == cid
    assert context.source == 'workspace'
    assert customer.uploaded_sources['PROCEDURE'] == ['hist:'+'a'*16]
    assert _inferred_bindings[('tenant', 'new-meeting')][0]['customer_id'] == cid

@pytest.mark.asyncio
async def test_conflicting_filename_and_unknown_folder_are_not_bound():
    from unittest.mock import Mock
    db = AsyncMock()
    db.execute.return_value = Mock()
    db.execute.return_value.scalars.return_value.all.return_value = [
        SimpleNamespace(relative_path='BP/notes.docx', source_file='notes.docx', file_hash='a'*64),
        SimpleNamespace(relative_path='BP/Chevron.docx', source_file='Chevron.docx', file_hash='b'*64),
        SimpleNamespace(relative_path='Unknown/notes.docx', source_file='notes.docx', file_hash='c'*64),
    ]
    catalog = await folder_catalog(db, Catalog(), tenant_id='tenant', meeting_id='meeting')
    assert [b['document_id'] for b in _inferred_bindings[('tenant','meeting')]] == ['hist:'+'a'*16]
    assert catalog.customers[0].id == 'bp'
