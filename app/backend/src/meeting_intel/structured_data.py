"""Typed, deterministic tabular execution; no generated SQL or eval."""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, Field


class RowFilter(BaseModel):
    column: str
    operator: Literal['eq', 'lt', 'le', 'gt', 'ge', 'month', 'year'] = 'eq'
    value: str | int | float
    kind: Literal['text', 'number', 'date'] = 'text'


class QueryPlan(BaseModel):
    operation: Literal['count', 'sum', 'average', 'table'] = 'count'
    column: str | None = None
    filters: list[RowFilter] = Field(default_factory=list)
    group_by: str | None = None
    sort_by: str | None = None
    descending: bool = False
    select: list[str] = Field(default_factory=list)


def execute(rows, plan: QueryPlan, columns: dict[str, str], date_format='%Y-%m-%d'):
    def value(row, logical):
        if logical not in columns or columns[logical] not in row:
            raise ValueError('missing_column')
        return row[columns[logical]]

    def typed(raw, kind):
        if raw is None:
            raise ValueError('missing_value')
        if kind == 'date':
            return raw.date() if isinstance(raw, datetime) else raw if isinstance(raw, date) else datetime.strptime(str(raw), date_format).date()
        if kind == 'number':
            try:
                number = Decimal(str(raw))
                if not number.is_finite():
                    raise ValueError('invalid_number')
                return number
            except InvalidOperation:
                raise ValueError('invalid_number') from None
        return str(raw)

    selected = list(rows)
    for f in plan.filters:
        filtered = []
        for row in selected:
            left = typed(value(row, f.column), 'date' if f.operator in ('month', 'year') else f.kind)
            right = int(f.value) if f.operator in ('month', 'year') else typed(f.value, f.kind)
            if f.operator in ('month', 'year'):
                left = getattr(left, f.operator)
            predicates = {'eq': lambda: left == right, 'lt': lambda: left < right, 'le': lambda: left <= right,
                          'gt': lambda: left > right, 'ge': lambda: left >= right,
                          'month': lambda: left == right, 'year': lambda: left == right}
            if predicates[f.operator]():
                filtered.append(row)
        selected = filtered
    if plan.operation == 'table':
        if not plan.select:
            raise ValueError('missing_projection')
        result = [{c: value(row, c) for c in plan.select} for row in selected]
    else:
        def aggregate(group):
            if plan.operation == 'count':
                return len(group)
            if not plan.column:
                raise ValueError('missing_measure')
            numbers = [typed(value(row, plan.column), 'number') for row in group]
            if plan.operation == 'average' and not numbers:
                raise ValueError('empty_average')
            total = sum(numbers, Decimal(0))
            return str(total / len(numbers) if plan.operation == 'average' else total)
        if not plan.group_by:
            return aggregate(selected)
        groups = defaultdict(list)
        for row in selected:
            groups[value(row, plan.group_by)].append(row)
        result = [{plan.group_by: group, 'value': aggregate(group_rows)} for group, group_rows in groups.items()]
    if plan.sort_by:
        if any(plan.sort_by not in row for row in result):
            raise ValueError('missing_sort_column')
        result.sort(key=lambda row: Decimal(str(row['value'])) if plan.sort_by == 'value' else row[plan.sort_by], reverse=plan.descending)
    return result


def render(value):
    if not isinstance(value, list):
        return str(value)
    if not value:
        return 'No matching records.'
    def safe(v):
        return str(v).replace('|', '\\|').replace('\n', ' ')
    keys = list(value[0])
    return '\n'.join([' | '.join(keys), ' | '.join('---' for _ in keys)] +
                     [' | '.join(safe(row[k]) for k in keys) for row in value])
