"""Meeting association for historical file import (§15-§16 of the upgrade
spec). Reuses `ingestion.pipeline.get_or_create_meeting` — the same
`Meeting` table live Teams meetings use — rather than a parallel
"historical meeting" model.

Association order:
  1. An explicit, real Teams Meeting ID supplied by the caller — preserved
     as-is (`Meeting.is_historical=False`; this is a real meeting, only its
     *documents* were imported historically).
  2. An exact (case-insensitive) title match against an existing meeting in
     the same tenant — deliberately exact, never fuzzy ("do not make weak
     guesses").
  3. Otherwise, a new historical meeting is created with a deterministic
     `historical_<hash>` id (§16), grouped by folder (files in the same
     folder become one meeting) or, for a file with no folder, by its own
     filename stem. The same folder/file therefore always maps to the same
     meeting id on a repeat import — never a random id.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.db.models import Meeting
from meeting_intel.ingestion.pipeline import get_or_create_meeting

_DATE_RE = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")

# Historical import processes files with bounded concurrency (see
# ingestion/historical_import.py), each in its own DB session — without
# this, two files destined for the same new meeting (e.g. a VTT and a
# supporting .docx in the same folder) can both miss the "does it exist"
# check and both try to INSERT it, tripping the
# uq_meetings_tenant_msid unique constraint. A per-tenant lock serializes
# only this resolve-or-create step (not parsing/embedding/indexing).
_tenant_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def deterministic_historical_id(*, tenant_id: str, key: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}:{key}".encode("utf-8")).hexdigest()[:16]
    return f"historical_{digest}"


def _humanize(name: str) -> str:
    cleaned = name.replace("_", " ").replace("-", " ").strip()
    return cleaned.title() if cleaned else name


def association_key(*, relative_path: str, filename: str) -> tuple[str, str]:
    """Returns (grouping_key, derived_title) — see module docstring §3."""
    parts = [p for p in relative_path.split("/")[:-1] if p]
    if parts:
        folder = parts[-1]
        title = _humanize(folder)
        date_match = _DATE_RE.search(folder)
        if date_match and date_match.group(0) not in title:
            title = f"{title} ({date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)})"
        return "/".join(parts), title
    stem = filename.rsplit(".", 1)[0]
    return stem, _humanize(stem)


async def resolve_meeting(
    db: AsyncSession,
    *,
    tenant_id: str,
    organizer_id: str | None,
    relative_path: str,
    filename: str,
    explicit_meeting_id: str | None = None,
    explicit_title: str | None = None,
) -> tuple[Meeting, bool]:
    """Returns (meeting, is_newly_historical)."""
    # Held until the meeting row is *committed*, not just flushed: another
    # concurrent task (its own DB session) resolving the same folder would
    # otherwise not see an uncommitted insert and would also try to create
    # it, tripping the same unique constraint the lock is meant to prevent.
    async with _tenant_locks[tenant_id]:
        if explicit_meeting_id:
            meeting = await get_or_create_meeting(
                db, tenant_id=tenant_id, ms_meeting_id=explicit_meeting_id,
                title=explicit_title or explicit_meeting_id, organizer_id=organizer_id,
            )
            await db.commit()
            return meeting, False

        key, derived_title = association_key(relative_path=relative_path, filename=filename)
        title = explicit_title or derived_title

        existing = (
            await db.execute(
                select(Meeting).where(Meeting.tenant_id == tenant_id, func.lower(Meeting.title) == title.lower())
            )
        ).scalars().first()
        if existing is not None:
            return existing, False

        historical_id = deterministic_historical_id(tenant_id=tenant_id, key=key)
        meeting = await get_or_create_meeting(
            db, tenant_id=tenant_id, ms_meeting_id=historical_id, title=title, organizer_id=organizer_id
        )
        if not meeting.is_historical:
            meeting.is_historical = True
        await db.commit()
        return meeting, True
