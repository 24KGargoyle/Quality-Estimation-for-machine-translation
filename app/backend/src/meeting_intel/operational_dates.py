"""Deterministic customer-local date resolution for structured operations."""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class DateRange:
    start: date | None
    end: date | None
    label: str


def resolve_date_range(query: str, *, today: date, upcoming_days: int = 7,
                       month_end_business_days: int = 5) -> DateRange | None:
    q = re.sub(r'\s+', ' ', query.casefold()).strip()
    if re.search(r'\btoday\b', q):
        return DateRange(today, today, today.isoformat())
    if re.search(r'\bthis week\b', q):
        start = today - timedelta(days=today.weekday())
        return DateRange(start, start + timedelta(days=6), 'this week')
    if re.search(r'\bthis month\b', q):
        start = today.replace(day=1)
        end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
        return DateRange(start, end, f'{today:%B %Y}')
    if re.search(r'\bnext month\b', q):
        year, month = (today.year + (today.month == 12), 1 if today.month == 12 else today.month + 1)
        start = date(year, month, 1)
        return DateRange(start, date(year, month, calendar.monthrange(year, month)[1]), f'{start:%B %Y}')
    if re.search(r'\b(overdue|past due)\b', q):
        return DateRange(None, today - timedelta(days=1), 'overdue (before today)')
    if re.search(r'\b(upcoming|expiring soon|due soon)\b', q):
        return DateRange(today, today + timedelta(days=max(0, upcoming_days)),
                         f'next {max(0, upcoming_days)} days')
    if re.search(r'\bmonth[ -]end\b', q):
        last_day = calendar.monthrange(today.year, today.month)[1]
        cursor = date(today.year, today.month, last_day)
        days = []
        while len(days) < max(1, month_end_business_days):
            if cursor.weekday() < 5:
                days.append(cursor)
            cursor -= timedelta(days=1)
        return DateRange(min(days), date(today.year, today.month, last_day),
                         f'last {len(days)} business days of {today:%B %Y}')
    month_names = '|'.join(calendar.month_name[1:])
    match = re.search(rf'\b({month_names})(?:\s+(20\d{{2}}))?\b', q, re.I)
    if match:
        month = list(calendar.month_name).index(match.group(1).capitalize())
        year = int(match.group(2)) if match.group(2) else today.year + (month < today.month)
        return DateRange(date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]),
                         f'{calendar.month_name[month]} {year}')
    return None
