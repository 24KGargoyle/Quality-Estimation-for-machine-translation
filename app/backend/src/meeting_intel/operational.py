"""Conservative operational routing over administrator-approved customer records.

No model-generated procedures or SQL. Unknown/ambiguous requests fail closed.
The catalog is trusted deployment configuration, never request supplied.
"""
from __future__ import annotations

import calendar
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal
from zoneinfo import ZoneInfo
from zipfile import BadZipFile

from pydantic import BaseModel, Field, ConfigDict, model_validator

from meeting_intel.agents.answer_agent import AnswerResult, answer_question
from meeting_intel.config import get_settings
from meeting_intel.structured_data import QueryPlan, execute, render

logger = logging.getLogger(__name__)
SOURCE_ROUTING = {
    'PROCEDURE': ['approved_sop'], 'ACCOUNT_INFO': ['customer_master', 'account_roster'],
    'STRUCTURED_DATA': ['structured_files', 'database'], 'REPORTING': ['reporting'],
    'SOW_TERMS': ['sow_doc'], 'PROJECT_SCOPE': ['sow_doc', 'project_doc'],
    'DAILY_TASKS': ['task_schedule', 'reporting', 'reporting_calendar', 'operational_calendar', 'account_context'],
    'GENERAL_KNOWLEDGE': ['existing_rag'], 'UNKNOWN': [],
}
SOURCE_PRIORITY = {
    'approved_sop': 0, 'database': 0, 'structured_files': 0,
    'sow_doc': 0, 'project_doc': 1, 'reporting': 0,
    'customer_master': 0, 'account_roster': 1,
    'sharepoint': 1, 'account_info': 2,
    'meeting': 3, 'teams_chat': 3, 'email': 3, 'historical': 4,
}


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    customer_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    source_type: str
    title: str
    topic: str
    aliases: list[str] = Field(default_factory=list)
    queries: dict[str, QueryPlan] = Field(default_factory=dict)
    status: str = 'draft'
    version: str = '1'
    effective_date: date
    last_updated: date | None = None
    expires_on: date | None = None
    authority_level: int = 100
    owner: str = ''
    document_id: str | None = None
    answer: str = ''
    steps: list[str] = Field(default_factory=list)
    rows: list[dict] = Field(default_factory=list)
    columns: dict[str, str] = Field(default_factory=dict)
    file: str | None = None
    sheet: str | None = None
    date_format: str = '%Y-%m-%d'
    role: str | None = None
    frequency: Literal['daily', 'weekly', 'monthly', 'date'] = 'daily'
    weekday: int | None = Field(default=None, ge=0, le=6)
    day: int | None = Field(default=None, ge=1, le=31)
    on_date: date | None = None

    @model_validator(mode='after')
    def validate_schedule(self):
        if self.source_type == 'task_schedule':
            required = {'weekly': self.weekday, 'monthly': self.day, 'date': self.on_date}
            if self.frequency in required and required[self.frequency] is None:
                raise ValueError('Missing schedule constraint')
        if self.expires_on and self.expires_on < self.effective_date:
            raise ValueError('Expiry precedes effective date')
        if self.last_updated and self.last_updated < self.effective_date:
            raise ValueError('Update date precedes effective date')
        return self


class Customer(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    meeting_ids: list[str] = Field(default_factory=list)
    user_ids: list[str] = Field(default_factory=list)
    roles: dict[str, str] = Field(default_factory=dict)
    timezone: str = 'UTC'
    sme: str | None = None
    uploaded_sources: dict[str, list[str]] = Field(default_factory=dict)


class Catalog(BaseModel):
    customers: list[Customer] = Field(default_factory=list)
    records: list[Record] = Field(default_factory=list)
    routing: dict[str, list[str]] = Field(default_factory=lambda: dict(SOURCE_ROUTING))
    document_bindings: list[dict[str, str]] = Field(default_factory=list)


@dataclass(frozen=True)
class CustomerContext:
    customer_id: str
    customer_name: str
    source: str


@dataclass(frozen=True)
class RoutingDecision:
    customer_id: str
    intent: str
    target_source: list[str]
    confidence: float


def mentions(query: str, phrase: str) -> bool:
    return bool(phrase.strip()) and bool(re.search(r'(?<!\w)' + re.escape(phrase.replace('_', ' ')) + r'(?!\w)', query, re.I))


def without_customer_name(query, customer):
    for name in sorted({customer.id, customer.name, *customer.aliases}, key=len, reverse=True):
        if name.strip():
            query = re.sub(r'(?<!\w)(?:for\s+)?' + re.escape(name) + r"(?:'s)?(?!\w)[:,]?", '', query, flags=re.I)
    return re.sub(r'\s+([?.!])', r'\1', re.sub(r'\s+', ' ', query)).strip()


def resolve_customer(query, customers, *, session_id=None, selected_id=None, meeting_id=None, user_id=None):
    # A deliberate selection or a customer named in the current turn changes
    # context; a stored conversation context only fills in an omitted customer.
    matches = [c for c in customers if any(mentions(query, a) for a in [c.id, c.name, *c.aliases])]
    if matches:
        if len(matches) != 1:
            return None, None
        c = matches[0]
        return c, CustomerContext(c.id, c.name, 'query')
    if selected_id:
        matches = [c for c in customers if c.id == selected_id]
        return (matches[0], CustomerContext(selected_id, matches[0].name, 'selection')) if len(matches) == 1 else (None, None)
    explicit_reference = re.search(
        r'\b(?:switch(?:ing)?\s+to|customer|account)\s+([A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*){0,4})',
        query,
    )
    if explicit_reference:
        # An unrecognized explicit account reference must not fall back to the
        # previous customer's context.
        return None, None
    if session_id:
        matches = [c for c in customers if c.id == session_id]
        return (matches[0], CustomerContext(session_id, matches[0].name, 'session')) if len(matches) == 1 else (None, None)
    # A meeting mapped to exactly one authorized customer supplies the
    # customer context automatically. Ambiguous or unmapped meetings still
    # require an explicit customer from the user.
    meeting_customers = [c for c in customers if meeting_id and meeting_id in c.meeting_ids]
    if len(meeting_customers) == 1:
        customer = meeting_customers[0]
        return customer, CustomerContext(customer.id, customer.name, 'meeting')
    return None, None


def mentions_unauthorized_customer(query, catalog, allowed, tenant_id):
    allowed_ids = {c.id for c in allowed}
    return any(
        c.id not in allowed_ids and any(mentions(query, alias) for alias in [c.id, c.name, *c.aliases])
        for c in catalog.customers if c.tenant_id == tenant_id
    )


async def browse_scope(*, db, user, meeting_id, query='', selected_id=None):
    """Keep explicit source browsing scoped without changing its response contract."""
    if not get_settings().operational_enabled:
        return {}
    from fastapi import HTTPException
    try:
        catalog = Catalog.model_validate_json(Path(get_settings().operational_catalog_path).read_text(encoding='utf-8'))
        from meeting_intel.folder_customer import folder_catalog
        catalog = await folder_catalog(db, catalog, tenant_id=user.tenant_id, meeting_id=meeting_id)
        allowed = [c for c in catalog.customers if c.tenant_id == user.tenant_id
                   and (meeting_id in c.meeting_ids or user.id in c.user_ids)]
        if mentions_unauthorized_customer(query, catalog, allowed, user.tenant_id):
            raise HTTPException(409, 'Customer context could not be resolved for this request.')
        customer, _ = resolve_customer(query, allowed, selected_id=selected_id, meeting_id=meeting_id, user_id=user.id)
    except (ValueError, OSError):
        raise HTTPException(503, 'Customer configuration is unavailable') from None
    if customer is None:
        raise HTTPException(409, 'Which customer are you asking about?')
    return {'customer_id': customer.id}


def classify_intent(query: str) -> str:
    q = query.lower()
    if re.search(r'\b(tasks?|checklist|reports?)\b', q) and re.search(r'\b(today|daily|do)\b', q):
        return 'DAILY_TASKS'
    if re.search(r'\b(how many|number of|count|sum|total|average|group by|sort)\b', q):
        return 'STRUCTURED_DATA'
    if re.search(r'\b(sow|statement of work)\b', q) and re.search(r'\b(expir\w*|renew\w*|overdue|upcoming|past due|due soon|amount|value|consultant|roster|list|show|number)\b', q):
        return 'STRUCTURED_DATA'
    if re.search(r'\b(sow|statement of work)\b', q) and re.search(r'\b(term|terms|clause|obligation|scope|deliverable|provision)\b', q):
        return 'SOW_TERMS'
    if re.search(r'\b(project scope|in scope|out of scope|scope of work)\b', q):
        return 'PROJECT_SCOPE'
    if re.search(r'\b(consultants?|roster)\b', q) and re.search(r'\b(list|show|who|which|how many|count|on|in)\b', q):
        return 'STRUCTURED_DATA'
    if re.search(r'\b(report|reporting|distribution list)\b', q):
        return 'REPORTING'
    if re.search(r'\b(account manager|account owner|sme|contact)\b', q):
        return 'ACCOUNT_INFO'
    if re.search(r'\b(how (do|can|should|to)|procedure|process|steps|sop)\b', q):
        return 'PROCEDURE'
    if re.search(r'\b(approve|submit|create|delete|change order|deadline|recipient|expire|expiry|schedule)\b', q):
        return 'UNKNOWN'
    return 'GENERAL_KNOWLEDGE'


def exact_topic(query, record, intent):
    normalized = query.strip().rstrip('?.!').casefold()
    if intent == 'PROCEDURE':
        normalized = re.sub(r'^(?:how (?:do|can|should) i|how to|what are the steps to|procedure for|steps to)\s+', '', normalized)
    elif intent == 'ACCOUNT_INFO':
        normalized = re.sub(r'^(?:who is|who\'s)\s+(?:the\s+)?', '', normalized)
    else:
        return any(mentions(query, a) for a in [record.topic, *record.aliases])
    return any(normalized == a.replace('_', ' ').strip().casefold() for a in [record.topic, *record.aliases])


class EvidenceStore:
    def __init__(self, catalog: Catalog, base: Path):
        self.catalog, self.base = catalog, base.resolve()

    def retrieve(self, *, tenant_id: str, customer_id: str, sources: list[str], today: date):
        if not customer_id:
            raise ValueError('Customer is required')
        candidates = [r for r in self.catalog.records if r.tenant_id == tenant_id and r.customer_id == customer_id
                and r.source_type in sources and r.status.casefold() in ('approved', 'active')
                and r.authority_level >= get_settings().operational_min_authority
                and r.effective_date <= today]
        # Expired replacements must not resurrect superseded versions.
        result = []
        for key in {(r.source_type, r.topic, r.role) for r in candidates}:
            group = [r for r in candidates if (r.source_type, r.topic, r.role) == key]
            latest = max((r.effective_date, version_key(r.version)) for r in group)
            result.extend(r for r in group if (r.effective_date, version_key(r.version)) == latest
                          and (r.expires_on is None or today <= r.expires_on))
        return result

    def rows(self, record: Record, *, customer_id: str):
        if record.customer_id != customer_id:
            raise ValueError('Customer mismatch')
        if not record.file:
            rows = record.rows
        else:
            path = (self.base / record.file).resolve()
            if not path.is_relative_to(self.base):
                raise ValueError('Dataset path outside catalog directory')
            if path.suffix.lower() == '.csv':
                import csv
                with path.open(encoding='utf-8-sig', newline='') as stream:
                    reader = csv.DictReader(stream)
                    headers = reader.fieldnames
                    if not headers or len(set(headers)) != len(headers) or not set(record.columns.values()).issubset(headers):
                        raise ValueError('invalid_dataset_schema')
                    rows = list(reader)
            elif path.suffix.lower() == '.xlsx':
                from openpyxl import load_workbook
                book = load_workbook(path, read_only=True, data_only=True)
                try:
                    sheet = book[record.sheet] if record.sheet else book.active
                    values = iter(sheet.values)
                    headers = next(values, None)
                    if not headers or len(set(headers)) != len(headers) or not set(record.columns.values()).issubset(headers):
                        raise ValueError('invalid_dataset_schema')
                    rows = [dict(zip(headers, row)) for row in values if any(v is not None for v in row)]
                finally:
                    book.close()
            else:
                raise ValueError('Unsupported dataset')
        # Mixed-customer files require an explicit customer column mapping.
        column = record.columns.get('customer_id')
        if column:
            if any(column not in row for row in rows):
                raise ValueError('Missing customer column')
            rows = [row for row in rows if row[column] == customer_id]
        return rows


def version_key(version):
    if not re.fullmatch(r'\d+(\.\d+)*', version):
        raise ValueError('invalid_version')
    parts = list(map(int, version.split('.')))
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def current_record(records):
    if not records:
        raise ValueError('missing_approved_evidence')
    def key(r):
        return r.effective_date, version_key(r.version), r.last_updated or r.effective_date
    best = max(map(key, records))
    matches = [r for r in records if key(r) == best]
    if len(matches) != 1:
        raise ValueError('conflicting_evidence')
    return matches[0]


def structured_answer(query, record, store, customer_id, today=None):
    """Deliberately bounded grammar: never silently ignore extra predicates."""
    plans = [plan for text, plan in record.queries.items() if text.strip().casefold() == query.strip().casefold()]
    if len(plans) == 1:
        rows = store.rows(record, customer_id=customer_id)
        value = execute(rows, plans[0], record.columns, record.date_format)
        result = render(value)
        if plans[0].operation == 'count' and isinstance(value, int):
            if value > 10:
                result += '\nMore than 10 records matched; narrow the filters for the full list.'
            else:
                projection = [key for key in record.columns if key != 'customer_id']
                if projection and value:
                    table = QueryPlan(operation='table', filters=plans[0].filters, select=projection)
                    result += '\n' + render(execute(rows, table, record.columns, record.date_format))
        return result + '\n\n' + _structured_source(record)
    today = today or date.today()
    expiry_column = record.columns.get('expiry_date')
    allowed_date_terms = {'how', 'many', 'show', 'list', 'which', 'what', 'are', 'the', 'sow', 'sows',
        'statement', 'of', 'work', 'expire', 'expires', 'expiring', 'expiration', 'expirations', 'expiry',
        'renew', 'renewal', 'overdue', 'past', 'due', 'upcoming', 'soon', 'this', 'next', 'month', 'week',
        'today', 'end', 'business', 'days', 'in', 'during'}
    month_terms = {name.casefold() for name in calendar.month_name[1:]}
    tokens = re.findall(r'[a-z]+|\d+', query.casefold())
    supported_tokens = all(token in (allowed_date_terms | month_terms)
                           or (token.isdigit() and len(token) == 4 and token.startswith('20'))
                           for token in tokens)
    if expiry_column and supported_tokens and re.search(r'\b(sow|statement of work)\b', query, re.I) and re.search(r'\b(expir\w*|renew\w*|overdue|past due|upcoming|due soon|today|this month|next month|this week|month[ -]end)\b', query, re.I):
        from meeting_intel.operational_dates import resolve_date_range
        date_range = resolve_date_range(query, today=today,
            upcoming_days=get_settings().upcoming_days,
            month_end_business_days=get_settings().month_end_business_days)
        if date_range:
            rows = store.rows(record, customer_id=customer_id)
            dated = []
            for row in rows:
                value = row.get(expiry_column)
                if value is None:
                    raise ValueError('missing_value')
                expiry = _dataset_date(value, record.date_format)
                if (date_range.start is None or expiry >= date_range.start) and expiry <= date_range.end:
                    dated.append(row)
            if date_range.start is None:
                resolved_period = f'{date_range.label}, through {date_range.end.isoformat()}'
            else:
                resolved_period = f'{date_range.label} ({date_range.start.isoformat()} through {date_range.end.isoformat()})'
            output = f'{len(dated)} SOWs expire {resolved_period}.'
            if len(dated) <= 10:
                visible = [key for key in record.columns if key != 'customer_id']
                if visible and dated:
                    output += '\n' + render([{key: row.get(record.columns[key]) for key in visible} for row in dated])
            else:
                output += '\nThere are more than 10 matching records; refine the date range for a detailed list.'
            return output + '\n\n' + _structured_source(record)
    months = '|'.join(calendar.month_name[1:])
    pattern = rf'\s*how many SOWs? expire in ({months})(?: (\d{{4}}))?\??\s*'
    match = re.fullmatch(pattern, query, re.I)
    if not match:
        raise ValueError('unsupported_structured_query')
    month = list(calendar.month_name).index(match[1].capitalize())
    column = record.columns.get('expiry_date')
    if not column:
        raise ValueError('missing_expiry_column')
    dates = []
    for row in store.rows(record, customer_id=customer_id):
        dates.append(_dataset_date(row[column], record.date_format))
    year = int(match[2]) if match[2] else None
    if year is None:
        year = today.year if month >= today.month else today.year + 1
    matches = [(row, expiry) for row, expiry in zip(store.rows(record, customer_id=customer_id), dates)
               if expiry.year == year and expiry.month == month]
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    label = f'{match[1].capitalize()} {year} ({start.isoformat()} through {end.isoformat()})'
    result = f'{len(matches)} SOWs expire in {label}.'
    if len(matches) <= 10:
        visible_columns = [column for column in record.columns if column != 'customer_id']
        if visible_columns:
            result += '\n' + render([
                {key: row.get(record.columns[key]) for key in visible_columns}
                for row, _ in matches
            ])
    return result + '\n\n' + _structured_source(record)


def operational_answer(query, intent, customer, records, store, today, role):
    if intent == 'DAILY_TASKS':
        applicable = []
        schedule_types = {'task_schedule', 'reporting', 'reporting_calendar', 'operational_calendar'}
        tasks = [r for r in records if r.source_type in schedule_types]
        if role is None and any(r.role for r in tasks):
            raise ValueError('missing_role')
        tasks = [r for r in tasks if r.role is None or r.role == role]
        task_keys = sorted({(r.source_type, r.topic, r.role) for r in tasks})
        for source_type, topic, task_role in task_keys:
            r = current_record([r for r in tasks if (r.source_type, r.topic, r.role) == (source_type, topic, task_role)])
            if r.role and role is None:
                raise ValueError('missing_role')
            if r.role and r.role != role:
                continue
            due = (r.frequency == 'daily' or r.frequency == 'weekly' and r.weekday == today.weekday()
                   or r.frequency == 'monthly' and r.day == today.day or r.frequency == 'date' and r.on_date == today)
            if due:
                if not r.answer:
                    raise ValueError('missing_task_instructions')
                applicable.append(r)
        if not applicable:
            raise ValueError('missing_task_schedule')
        text = f"Today's {customer.name}{' ' + role if role else ''} tasks:\n\n" + '\n'.join(
            f'{i}. {r.answer}' for i, r in enumerate(applicable, 1))
        return text + '\n\n' + '\n'.join(_record_source(r) for r in applicable), applicable
    matches = [r for r in records if exact_topic(query, r, intent)
               or any(q.strip().casefold() == query.strip().casefold() for q in r.queries)]
    if intent in ('PROCEDURE', 'ACCOUNT_INFO', 'REPORTING', 'SOW_TERMS', 'PROJECT_SCOPE'):
        if role is None and any(r.role for r in matches):
            raise ValueError('missing_role')
        matches = [r for r in matches if r.role is None or r.role == role]
    if matches:
        priority = min(SOURCE_PRIORITY.get(r.source_type, 100) for r in matches)
        matches = [r for r in matches if SOURCE_PRIORITY.get(r.source_type, 100) == priority]
    if len({r.topic for r in matches}) != 1:
        raise ValueError('missing_or_ambiguous_topic')
    r = current_record(matches)
    if intent == 'STRUCTURED_DATA':
        return structured_answer(query, r, store, customer.id, today), [r]
    if intent == 'PROCEDURE' and r.steps:
        return ('\n'.join(f'{i}. {s}' for i, s in enumerate(r.steps, 1)) +
                f'\n\nSource: {r.title}, version {r.version}, effective {r.effective_date.isoformat()}'), [r]
    if intent == 'ACCOUNT_INFO' and r.answer:
        return r.answer + '\n\n' + _record_source(r), [r]
    if intent == 'REPORTING' and r.answer:
        return r.answer + '\n\n' + _record_source(r), [r]
    if intent in ('SOW_TERMS', 'PROJECT_SCOPE') and r.answer:
        return r.answer + '\n\n' + _record_source(r), [r]
    raise ValueError('insufficient_evidence')


def _record_source(record):
    return f"Source: {record.title}, version {record.version}, effective {record.effective_date.isoformat()}"


def _structured_source(record):
    updated = record.last_updated.isoformat() if record.last_updated else 'date not provided'
    return f'Source: {record.title}, last updated {updated}'


def _dataset_date(value, date_format):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), date_format).date()
    except (TypeError, ValueError):
        raise ValueError('invalid_date') from None


async def handle_query(db, *, meeting, user, history, question, conversation, selected_id=None, document=None, request_id=None):
    started = perf_counter()
    trace = dict(request_id=request_id, customer_id=None, intent='UNKNOWN', selected_source=[],
                 retrieved_document_ids=[], authority=[], status=[], retrieval_score=None, confidence='LOW',
                 structured_query_used=False, answer_generated=False, fallback_triggered=True, fallback_reason=None)
    customer = None
    records = []
    operational_query = question
    intent = 'UNKNOWN'
    try:
        from meeting_intel.web_research.provider import (
            WebResearchNotConfiguredError, extract_research_topic,
            get_web_research_provider, should_research_web,
        )
        if should_research_web(question):
            topic = extract_research_topic(question)
            try:
                research = await get_web_research_provider().research(topic)
            except WebResearchNotConfiguredError:
                research = None
            if not research or not research.configured:
                return AnswerResult(text=("I don't have enough information to answer this accurately.\n\n"
                    "Missing: an available public web research source."), evidence_sufficient=False,
                    model='public-web-research', retrieval_query=topic)
            if not research.results:
                return AnswerResult(text=f"I couldn't find relevant public sources for {topic}.",
                    evidence_sufficient=False, model='public-web-research', retrieval_query=topic)
            lines = ['From public sources:']
            for item in research.results:
                lines.append(f'- [{item.title}]({item.url})' + (f' — {item.snippet}' if item.snippet else ''))
            return AnswerResult(text='\n'.join(lines), evidence_sufficient=True,
                model='public-web-research', retrieval_query=topic)
        path = Path(get_settings().operational_catalog_path)
        catalog = Catalog.model_validate_json(path.read_text(encoding='utf-8'))
        from meeting_intel.folder_customer import folder_catalog
        catalog = await folder_catalog(db, catalog, tenant_id=user.tenant_id, meeting_id=meeting.id)
        allowed = [c for c in catalog.customers if c.tenant_id == user.tenant_id
                   and (meeting.id in c.meeting_ids or user.id in c.user_ids)]
        if mentions_unauthorized_customer(question, catalog, allowed, user.tenant_id):
            trace['fallback_reason'] = 'customer_unresolved'
            return AnswerResult(text='I couldn\'t resolve that customer in your authorized account context.',
                                evidence_sufficient=False)
        customer, context = resolve_customer(question, allowed, session_id=conversation.customer_id,
                                            selected_id=selected_id, meeting_id=meeting.id, user_id=user.id)
        if customer is None:
            trace['fallback_reason'] = 'customer_unresolved'
            explicit_names = [c for c in allowed if any(mentions(question, a) for a in [c.id, c.name, *c.aliases])]
            if not explicit_names and not selected_id and not conversation.customer_id:
                return AnswerResult(text='Which customer are you asking about?', evidence_sufficient=False)
            return AnswerResult(text='I couldn\'t resolve that customer in your authorized account context.', evidence_sufficient=False)
        switching = bool(conversation.customer_id and conversation.customer_id != customer.id)
        conversation.customer_id = customer.id
        operational_query = without_customer_name(question, customer)
        intent = classify_intent(operational_query)
        # Exact administrator-reviewed query plans take precedence over heuristics.
        if any(r.tenant_id == user.tenant_id and r.customer_id == customer.id
               and r.source_type in ('structured_files', 'database')
               and any(q.strip().casefold() == operational_query.strip().casefold() for q in r.queries)
               for r in catalog.records):
            intent = 'STRUCTURED_DATA'
        sources = catalog.routing.get(intent, [])
        if any(source not in SOURCE_ROUTING[intent] for source in sources):
            raise ValueError('invalid_source_route')
        decision = RoutingDecision(customer.id, intent, sources, 0.0 if intent == 'UNKNOWN' else 1.0)
        trace.update(customer_id=customer.id, intent=intent, selected_source=sources)
        if intent == 'GENERAL_KNOWLEDGE' and sources == ['existing_rag']:
            # Never carry facts from the previous account into a switched context.
            result = await answer_question(db, meeting=meeting, user=user, history=[] if switching else history, question=question,
                                           document=document, customer_id=customer.id)
            trace.update(answer_generated=result.evidence_sufficient, fallback_triggered=not result.evidence_sufficient,
                         confidence='MEDIUM' if result.evidence_sufficient else 'LOW',
                         retrieved_document_ids=[r.chunk.id for r in result.retrieved_chunks],
                         retrieval_score=[r.score for r in result.retrieved_chunks],
                         fallback_reason=None if result.evidence_sufficient else 'insufficient_general_evidence')
            if not result.evidence_sufficient:
                contact = customer.sme or f'the {customer.name} account SME or account manager'
                if re.search(r'\b(meeting|transcript|attendee|participant|speaker|discussed|decided|decision|action item|what did)\b', question, re.I):
                    result.text = ("I couldn't find that topic in the available meeting records.\n\n"
                                   f"Meeting: {meeting.title}, {meeting.scheduled_start.date().isoformat() if meeting.scheduled_start else 'date unavailable'}\n"
                                   f"Contact: {contact}")
                else:
                    result.text = ("I don't have enough information to answer this accurately.\n\n"
                                   f"Missing: reliable {customer.name} evidence for this request.\n\nContact: {contact}")
            elif re.search(r'\b(meeting|transcript|attendee|participant|speaker|discussed|decided|decision|action item|what did)\b', question, re.I):
                date_label = meeting.scheduled_start.date().isoformat() if meeting.scheduled_start else 'date unavailable'
                result.text += f'\n\nMeeting: {meeting.title}, {date_label}'
            if switching:
                result.text = f'Switching to {customer.name}.\n\n{result.text}'
            return result
        today = datetime.now(ZoneInfo(customer.timezone)).date()
        store = EvidenceStore(catalog, path.parent)
        records = store.retrieve(tenant_id=user.tenant_id, customer_id=customer.id, sources=sources, today=today)
        if document is not None:
            records = [r for r in records if r.document_id == f'hist:{document.file_hash[:16]}']
        trace.update(retrieved_document_ids=[r.id for r in records], authority=[r.authority_level for r in records],
                     status=[r.status for r in records], routing_confidence=decision.confidence)
        trace['structured_query_used'] = intent == 'STRUCTURED_DATA'
        if (get_settings().operational_uploaded_evidence_enabled and not records
                and intent in ('PROCEDURE', 'ACCOUNT_INFO', 'DAILY_TASKS')):
            from meeting_intel.uploaded_operational import answer_uploaded
            result = await answer_uploaded(db, meeting=meeting, user=user, customer=customer,
                                          question=operational_query, intent=intent, today=today, document=document)
            trace.update(selected_source=['uploaded_documents'], confidence='MEDIUM' if result.evidence_sufficient else 'LOW',
                         status=['uploaded; approval not established'], authority=[],
                         retrieved_document_ids=[r.chunk.id for r in result.retrieved_chunks],
                         answer_generated=result.evidence_sufficient, fallback_triggered=not result.evidence_sufficient,
                         fallback_reason=None if result.evidence_sufficient else 'insufficient_uploaded_evidence')
            return result
        text, evidence = operational_answer(operational_query, intent, customer, records, store, today, customer.roles.get(user.id))
        trace.update(retrieved_document_ids=[r.id for r in evidence], authority=[r.authority_level for r in evidence],
                     status=[r.status for r in evidence], confidence='HIGH', answer_generated=True, fallback_triggered=False)
        if switching:
            text = f'Switching to {customer.name}.\n\n{text}'
        return AnswerResult(text=text, model='deterministic-operational')
    except (ValueError, OSError, KeyError, TypeError, BadZipFile) as exc:
        # Do not log exception text: validation errors can contain document data.
        safe_reasons = {'missing_approved_evidence', 'conflicting_evidence', 'invalid_version',
                        'missing_role', 'missing_task_instructions', 'missing_task_schedule',
                        'missing_or_ambiguous_topic', 'insufficient_evidence', 'unsupported_structured_query',
                        'missing_expiry_column', 'ambiguous_year', 'missing_column', 'missing_value',
                        'invalid_date',
                        'invalid_number', 'empty_average', 'missing_projection', 'missing_measure', 'missing_sort_column',
                        'invalid_source_route', 'invalid_dataset_schema'}
        trace['fallback_reason'] = str(exc) if str(exc) in safe_reasons else type(exc).__name__
        name = customer.name if customer else 'customer'
        contact = customer.sme if customer and customer.sme else f'the {name} account SME or account manager'
        if customer and trace['fallback_reason'] == 'conflicting_evidence':
            relevant = [r for r in records if r.source_type in SOURCE_ROUTING.get(intent, [])
                        and (exact_topic(operational_query, r, intent)
                             or any(q.strip().casefold() == operational_query.strip().casefold() for q in r.queries))]
            owners = sorted({r.owner.strip() for r in relevant if r.owner.strip()})
            if len(owners) == 1:
                contact = owners[0]
        reason_text = {
            'missing_role': f"What's your role on the {name} account?",
            'missing_or_ambiguous_topic': 'The relevant approved source or exact topic is missing or ambiguous.',
            'conflicting_evidence': 'The approved records conflict or have the same effective version.',
            'missing_approved_evidence': 'No approved current source was found.',
            'missing_task_schedule': 'The customer task schedule is missing.',
            'unsupported_structured_query': 'The structured dataset does not have an approved query for this request.',
            'missing_expiry_column': 'The structured dataset is missing its expiry date column.',
            'missing_column': 'A required structured dataset column is missing.',
            'missing_value': 'A required structured dataset value is missing.',
            'invalid_date': 'One or more structured dates are missing or invalid.',
            'invalid_dataset_schema': 'The dataset columns do not match the approved mapping.',
            'invalid_number': 'A required numeric dataset value is invalid.',
            'ambiguous_year': 'The request could not be resolved to one reporting year.',
        }.get(trace['fallback_reason'], 'Reliable evidence for this request is missing.')
        return AnswerResult(text=("I don't have enough information to answer this accurately.\n\n"
                                 f"Missing: {reason_text}\n\nContact: {contact}"), evidence_sufficient=False)
    finally:
        trace['latency'] = round((perf_counter() - started) * 1000)
        logger.info('operational_query %s', json.dumps(trace))
