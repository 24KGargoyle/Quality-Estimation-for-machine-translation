from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from meeting_intel.operational import (
    Catalog, Customer, EvidenceStore, Record, SOURCE_ROUTING, classify_intent,
    current_record, handle_query, operational_answer, resolve_customer, structured_answer,
    without_customer_name,
)
from meeting_intel.structured_data import QueryPlan, RowFilter, execute

TODAY = date(2026, 9, 24)
BP = Customer(id='bp', name='British Petroleum', tenant_id='t', meeting_ids=['m'])


def record(**kwargs):
    data = dict(id='sop', customer_id='bp', tenant_id='t', source_type='approved_sop',
                title='BP Change Order SOP', topic='change_order', status='approved',
                aliases=['create a change order'],
                effective_date='2026-01-01', steps=['Open the approved form.', 'Submit to the documented approver.'])
    return Record(**(data | kwargs))


def store(records):
    return EvidenceStore(Catalog(customers=[BP], records=records), Path('.'))


def answer(query, records, role=None):
    intent = classify_intent(query)
    service = store(records)
    scoped = service.retrieve(tenant_id='t', customer_id='bp', sources=SOURCE_ROUTING[intent], today=TODAY)
    return operational_answer(query, intent, BP, scoped, service, TODAY, role)[0]


@pytest.mark.parametrize('question,intent', [
    ('How do I create a change order?', 'PROCEDURE'),
    ('Who is the account manager?', 'ACCOUNT_INFO'),
    ('How many SOWs expire in September?', 'STRUCTURED_DATA'),
    ('What tasks should I do today?', 'DAILY_TASKS'),
    ('Summarize the discussion', 'GENERAL_KNOWLEDGE'),
])
def test_intents(question, intent):
    assert classify_intent(question) == intent


def test_context_priority_and_ambiguity():
    other = Customer(id='other', name='Other', tenant_id='t', meeting_ids=['m'])
    c, ctx = resolve_customer('Other', [BP, other], session_id='bp', meeting_id='m')
    assert c == BP and ctx.source == 'session'
    assert resolve_customer('BP Other', [BP, other])[0] is None
    assert resolve_customer('hello', [BP, other], meeting_id='m')[0] is None
    assert resolve_customer('BP', [BP], selected_id='not-authorized')[0] is None


@pytest.mark.parametrize('query', ['How many BP SOWs expire in September?',
                                  'How many SOWs expire in September for BP?',
                                  'BP: How many SOWs expire in September?'])
def test_explicit_customer_in_query(query):
    assert without_customer_name(query, BP) == 'How many SOWs expire in September?'


def test_procedure_precision_and_isolation():
    text = answer('How do I create a change order?', [record(),
                  record(id='war', topic='work_at_risk', aliases=[], steps=['WRONG WAR']),
                  record(id='other', customer_id='other', steps=['WRONG CUSTOMER']),
                  record(id='tenant', tenant_id='other', steps=['WRONG TENANT'])])
    assert 'Open the approved form' in text and 'WRONG' not in text


@pytest.mark.parametrize('bad', [dict(status='draft'), dict(effective_date='2027-01-01'),
                                dict(expires_on='2026-01-02'), dict(topic='work_at_risk', aliases=[]),
                                dict(authority_level=20)])
def test_missing_low_confidence_or_outdated_abstains(bad):
    with pytest.raises(ValueError):
        answer('How do I create a change order?', [record(**bad)])


def test_current_version_wins_and_conflicts_abstain():
    old = record(id='old', version='1', steps=['OLD'])
    new = record(id='new', version='3.1', steps=['CURRENT'])
    assert 'CURRENT' in answer('How do I create a change order?', [old, new])
    with pytest.raises(ValueError, match='conflicting'):
        current_record([new, record(id='duplicate', version='3.1')])


def test_expired_replacement_and_wrong_action_abstain():
    with pytest.raises(ValueError):
        answer('How do I create a change order?', [record(), record(id='new', version='2', expires_on='2026-09-01')])
    with pytest.raises(ValueError):
        answer('How do I delete a change order?', [record()])


def test_csv_and_excel_customer_rows(tmp_path):
    from openpyxl import Workbook
    csv = tmp_path / 'roster.csv'
    csv.write_text('Customer,Expiry\nbp,2026-09-24\nother,2026-09-24\n', encoding='utf-8')
    r = record(file='roster.csv', columns={'customer_id': 'Customer', 'expiry_date': 'Expiry'})
    service = EvidenceStore(Catalog(records=[r]), tmp_path)
    assert structured_answer('How many SOWs expire in September?', r, service, 'bp') == '1 SOWs expire in September.'
    book = Workbook()
    book.active.append(['Customer', 'Expiry'])
    book.active.append(['bp', TODAY])
    book.active.append(['other', TODAY])
    book.save(tmp_path / 'roster.xlsx')
    r.file = 'roster.xlsx'
    assert structured_answer('How many SOWs expire in September?', r, service, 'bp').startswith('1 ')
    r.file = '../outside.csv'
    with pytest.raises(ValueError, match='outside'):
        service.rows(r, customer_id='bp')
    r.file = 'roster.csv'
    csv.write_text('Customer,Expiry,Expiry\nbp,2026-09-01,2026-10-01\n', encoding='utf-8')
    with pytest.raises(ValueError, match='invalid_dataset_schema'):
        service.rows(r, customer_id='bp')


def test_empty_customer_rejected():
    with pytest.raises(ValueError):
        Customer(id='', name='Missing', tenant_id='t')


def test_account_lookup():
    text = answer('Who is the account manager?', [record(source_type='customer_master',
                  topic='account_manager', answer='Example Manager')])
    assert text.startswith('Example Manager')


def test_structured_count_and_ambiguous_year():
    r = record(source_type='structured_files', topic='sow', aliases=['SOWs'],
               columns={'expiry_date': 'SOW Expiry Date'}, rows=[
                   {'SOW Expiry Date': '2026-09-01'}, {'SOW Expiry Date': '2026-09-30'},
                   {'SOW Expiry Date': '2026-10-01'}])
    assert answer('How many SOWs expire in September?', [r]) == '2 SOWs expire in September.'
    with pytest.raises(ValueError, match='unsupported'):
        structured_answer('How many SOWs expire in September with status open?', r, store([r]), 'bp')
    r.rows.append({'SOW Expiry Date': '2025-09-01'})
    with pytest.raises(ValueError, match='ambiguous_year'):
        answer('How many SOWs expire in September?', [r])


def test_tasks_combine_schedule_and_role():
    records = [record(id='daily', source_type='task_schedule', topic='tracker', answer='Review tracker.'),
               record(id='weekly', source_type='task_schedule', topic='report', answer='Send report.',
                      frequency='weekly', weekday=3, role='Project Coordinator'),
               record(id='monthly', source_type='task_schedule', topic='review', answer='Review expiries.',
                      frequency='monthly', day=24),
               record(id='other', source_type='task_schedule', topic='other', answer='WRONG ROLE', role='Director')]
    text = answer('What tasks should I do today?', records, 'Project Coordinator')
    assert all(s in text for s in ['Review tracker.', 'Send report.', 'Review expiries.'])
    assert 'WRONG' not in text
    with pytest.raises(ValueError, match='missing_role'):
        answer('What tasks should I do today?', records)


def test_group_aggregate_sort_and_filter():
    rows = [{'Team': 'A', 'Amount': '3'}, {'Team': 'B', 'Amount': '9'}, {'Team': 'A', 'Amount': '4'}]
    columns = {'team': 'Team', 'amount': 'Amount'}
    plan = QueryPlan(operation='sum', column='amount', group_by='team', sort_by='value', descending=True)
    assert execute(rows, plan, columns) == [{'team': 'B', 'value': '9'}, {'team': 'A', 'value': '7'}]
    plan = QueryPlan(filters=[RowFilter(column='amount', kind='number', operator='gt', value=3)])
    assert execute(rows, plan, columns) == 2


@pytest.mark.asyncio
async def test_memory_customer_filter_before_ranking():
    from meeting_intel.retrieval.memory_search import InMemorySearchProvider
    from meeting_intel.retrieval.search_provider import IndexableChunk
    provider = InMemorySearchProvider()
    await provider.index_chunks([IndexableChunk(id=str(i), tenant_id='t', meeting_id='m', meeting_title='M',
        content='customer evidence', chunk_index=i, start_time=0, end_time=0, document_id=str(i),
        customer_id=c) for i, c in enumerate(['bp', 'other', None])])
    hits = await provider.hybrid_search(tenant_id='t', meeting_ids=['m'], query='customer', top_k=8, customer_id='bp')
    assert [h.id for h in hits] == ['0']


@pytest.mark.asyncio
async def test_azure_customer_filter(monkeypatch):
    from meeting_intel.retrieval.azure_search import AzureAISearchProvider
    provider = AzureAISearchProvider()
    captured = {}
    async def request(method, path, body):
        captured.update(body)
        return {'value': []}
    monkeypatch.setattr(provider, '_request', request)
    await provider.hybrid_search(tenant_id='t', meeting_ids=['m'], query='test', top_k=5, customer_id="bp'", vector=[1])
    assert "customer_id eq 'bp'''" in captured['filter']
    assert captured['vectorFilterMode'] == 'preFilter'


@pytest.mark.asyncio
async def test_orchestration_fallback_and_no_unresolved_retrieval(monkeypatch, tmp_path, caplog):
    from meeting_intel.config import get_settings
    path = tmp_path / 'catalog.json'
    path.write_text(Catalog(customers=[BP]).model_dump_json())
    monkeypatch.setattr(get_settings(), 'operational_catalog_path', str(path))
    conversation = SimpleNamespace(customer_id=None)
    caplog.set_level('INFO', logger='meeting_intel.operational')
    result = await handle_query(None, meeting=SimpleNamespace(id='m'), user=SimpleNamespace(id='u', tenant_id='t'),
                               history=[], question='How do I create a change order?', conversation=conversation)
    assert not result.evidence_sufficient and 'account SME' in result.text
    assert conversation.customer_id == 'bp'
    assert 'missing_or_ambiguous_topic' in caplog.text
    assert 'How do I create' not in caplog.text
    def forbidden(*args, **kwargs):
        raise AssertionError('retrieval before customer resolution')
    monkeypatch.setattr(EvidenceStore, 'retrieve', forbidden)
    result = await handle_query(None, meeting=SimpleNamespace(id='no-access'), user=SimpleNamespace(id='u', tenant_id='t'),
                               history=[], question='BP', conversation=SimpleNamespace(customer_id=None))
    assert 'select a customer' in result.text
