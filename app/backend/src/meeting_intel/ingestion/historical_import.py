"""Historical Meeting Data Import — the batch pipeline behind
`POST /api/historical-imports` (§18 of the upgrade spec).

One corrupt/unsupported file never aborts the batch (§37): each file is
processed independently, in its own database session (bounded concurrency
via `settings.import_max_concurrency`), and gets its own
`ImportedFileResult` row recording success/skipped/failed/duplicate — never
silently discarded.

There is no separate job queue/worker process in this environment (no
Celery/Redis available) — a job runs as an `asyncio.create_task` inside the
same backend process, tracked via the `HistoricalImportJob` row so progress
can be polled over HTTP. This means a job in flight is lost if the process
restarts mid-import (not a durable queue) — see docs/HISTORICAL_IMPORT.md
for this documented limitation and how to add a real queue in production.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.config import get_settings
from meeting_intel.db.models import (
    HistoricalDocument,
    HistoricalImportJob,
    ImportedFileResult,
    ImportFileStatus,
    ImportJobStatus,
    Meeting,
    MeetingStatus,
)
from meeting_intel.db.session import SessionLocal
from meeting_intel.ingestion.documents import NormalizedDocument, UnsupportedFileError
from meeting_intel.ingestion.meeting_association import resolve_meeting
from meeting_intel.ingestion.parsers import ParserFactory, SUPPORTED_EXTENSIONS
from meeting_intel.providers import get_embedding_provider
from meeting_intel.retrieval.hybrid_search import get_search_provider
from meeting_intel.retrieval.search_provider import IndexableChunk
from meeting_intel.security.file_safety import file_hash as compute_file_hash
from meeting_intel.storage.blob_storage import BlobStorageNotConfiguredError, get_blob_storage

logger = logging.getLogger("meeting_intel.historical_import")


@dataclass
class StagedFile:
    """A file already read into memory and safety-checked by the API layer
    (size limit, sanitized filename/relative_path) before the background job
    starts — see api/routers/historical_imports.py."""

    filename: str
    relative_path: str
    content: bytes
    explicit_meeting_id: str | None = None


def file_type_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


async def detect_files(files: list[StagedFile]) -> dict[str, int]:
    """The pre-upload detection summary (§19): counts per extension, plus
    how many are entirely unsupported."""
    counts: dict[str, int] = {}
    for f in files:
        ext = file_type_of(f.filename)
        key = ext if ParserFactory.is_supported(ext) else "unsupported"
        counts[key] = counts.get(key, 0) + 1
    return counts


async def create_import_job(db: AsyncSession, *, tenant_id: str, user_id: str, total_files: int) -> HistoricalImportJob:
    job = HistoricalImportJob(
        tenant_id=tenant_id, created_by=user_id, status=ImportJobStatus.queued, total_files=total_files,
    )
    db.add(job)
    await db.flush()
    return job


async def _bump(job_id: str, **increments: int) -> None:
    async with SessionLocal() as db:
        values = {k: getattr(HistoricalImportJob, k) + v for k, v in increments.items()}
        await db.execute(update(HistoricalImportJob).where(HistoricalImportJob.id == job_id).values(**values))
        await db.commit()


async def _set_current_file(job_id: str, filename: str) -> None:
    async with SessionLocal() as db:
        await db.execute(
            update(HistoricalImportJob).where(HistoricalImportJob.id == job_id).values(current_file=filename)
        )
        await db.commit()


def _recommended_action(reason: str, file_type: str) -> str:
    if file_type == "doc":
        return "Convert to .docx and re-upload."
    if file_type == "xls":
        return "Convert to .xlsx and re-upload."
    if "OCR" in reason:
        return "Run OCR on this PDF, or re-upload it as searchable text."
    if "password" in reason.lower():
        return "Remove the password protection and re-upload."
    if not ParserFactory.is_supported(file_type):
        return f"'.{file_type}' is not a supported format — see docs/HISTORICAL_IMPORT.md."
    return "Check the file opens correctly in its native application and re-upload."


async def _index_documents(
    documents: list[NormalizedDocument], *, tenant_id: str, meeting: Meeting, source_label: str, document_id_prefix: str
) -> int:
    if not documents:
        return 0
    vectors = get_embedding_provider().embed_texts([d.content for d in documents])
    chunks = [
        IndexableChunk(
            id=f"{document_id_prefix}:{i}",
            tenant_id=tenant_id,
            meeting_id=meeting.id,
            meeting_title=meeting.title,
            content=doc.content,
            chunk_index=i,
            start_time=doc.start_time or 0.0,
            end_time=doc.end_time or 0.0,
            document_id=document_id_prefix,
            speaker_name=doc.speaker,
            content_type=doc.document_type,
            source=source_label,
            source_file=doc.source_file,
            relative_path=doc.relative_path,
            file_type=doc.file_type,
            document_type=doc.document_type,
            page_number=doc.page_number,
            sheet_name=doc.sheet_name,
            slide_number=doc.slide_number,
            section=doc.section,
            embedding=vector,
        )
        for i, (doc, vector) in enumerate(zip(documents, vectors))
    ]
    await get_search_provider().index_chunks(chunks)
    return len(chunks)


async def _process_one(job_id: str, tenant_id: str, user_id: str, staged: StagedFile, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        await _set_current_file(job_id, staged.relative_path or staged.filename)
        file_type = file_type_of(staged.filename)
        h = compute_file_hash(staged.content)

        async with SessionLocal() as db:
            try:
                if not ParserFactory.is_supported(file_type):
                    db.add(ImportedFileResult(
                        import_job_id=job_id, filename=staged.filename, relative_path=staged.relative_path,
                        file_type=file_type or "unknown", status=ImportFileStatus.skipped,
                        reason=f"Unsupported file type: '.{file_type}'" if file_type else "No file extension",
                        recommended_action=_recommended_action("unsupported", file_type),
                    ))
                    await db.commit()
                    await _bump(job_id, processed_files=1, skipped_files=1)
                    return

                existing = (
                    await db.execute(
                        select(HistoricalDocument).where(
                            HistoricalDocument.tenant_id == tenant_id, HistoricalDocument.file_hash == h
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    db.add(ImportedFileResult(
                        import_job_id=job_id, filename=staged.filename, relative_path=staged.relative_path,
                        file_type=file_type, status=ImportFileStatus.duplicate,
                        reason="Already imported (identical file content).",
                        document_id=existing.id, meeting_id=existing.meeting_id, chunk_count=existing.chunk_count,
                    ))
                    await db.commit()
                    await _bump(job_id, processed_files=1, skipped_files=1)
                    return

                meeting, _ = await resolve_meeting(
                    db, tenant_id=tenant_id, organizer_id=user_id,
                    relative_path=staged.relative_path, filename=staged.filename,
                    explicit_meeting_id=staged.explicit_meeting_id,
                )

                parser = ParserFactory.get_parser(file_type)
                document_id_prefix = f"hist:{h[:16]}"
                try:
                    result = parser.parse(
                        content=staged.content, filename=staged.filename, relative_path=staged.relative_path,
                        tenant_id=tenant_id, meeting_id=meeting.id, title=meeting.title,
                        document_id_prefix=document_id_prefix,
                    )
                except UnsupportedFileError as exc:
                    db.add(ImportedFileResult(
                        import_job_id=job_id, filename=staged.filename, relative_path=staged.relative_path,
                        file_type=file_type, status=ImportFileStatus.skipped, reason=str(exc),
                        recommended_action=_recommended_action(str(exc), file_type), meeting_id=meeting.id,
                    ))
                    await db.commit()
                    await _bump(job_id, processed_files=1, skipped_files=1)
                    return

                if not result.documents:
                    reason = "; ".join(result.warnings) or "No extractable content."
                    db.add(ImportedFileResult(
                        import_job_id=job_id, filename=staged.filename, relative_path=staged.relative_path,
                        file_type=file_type, status=ImportFileStatus.skipped, reason=reason,
                        recommended_action=_recommended_action(reason, file_type), meeting_id=meeting.id,
                    ))
                    await db.commit()
                    await _bump(job_id, processed_files=1, skipped_files=1)
                    return

                chunk_count = await _index_documents(
                    result.documents, tenant_id=tenant_id, meeting=meeting,
                    source_label="historical_import", document_id_prefix=document_id_prefix,
                )

                try:
                    blob_path = await get_blob_storage().save(
                        path=f"{tenant_id}/{h}_{staged.filename}", content=staged.content
                    )
                except BlobStorageNotConfiguredError:
                    blob_path = None

                doc_row = HistoricalDocument(
                    tenant_id=tenant_id, meeting_id=meeting.id, import_job_id=job_id,
                    source_file=staged.filename, relative_path=staged.relative_path, file_type=file_type,
                    document_type=result.documents[0].document_type, file_hash=h, blob_path=blob_path,
                    size_bytes=len(staged.content), chunk_count=chunk_count,
                )
                db.add(doc_row)
                try:
                    await db.flush()
                except IntegrityError:
                    # Lost a race with a concurrent task importing the exact
                    # same file content (e.g. the same file listed twice in
                    # one folder selection) — the chunks we already indexed
                    # are safe (same deterministic ids, so re-indexing them
                    # is an idempotent overwrite, not a duplicate), but the
                    # HistoricalDocument row itself is now the winner's, not
                    # ours. Record this file as a duplicate of that row.
                    await db.rollback()
                    async with SessionLocal() as dup_db:
                        winner = (
                            await dup_db.execute(
                                select(HistoricalDocument).where(
                                    HistoricalDocument.tenant_id == tenant_id, HistoricalDocument.file_hash == h
                                )
                            )
                        ).scalar_one()
                        dup_db.add(ImportedFileResult(
                            import_job_id=job_id, filename=staged.filename, relative_path=staged.relative_path,
                            file_type=file_type, status=ImportFileStatus.duplicate,
                            reason="Already imported (identical file content).",
                            document_id=winner.id, meeting_id=winner.meeting_id, chunk_count=winner.chunk_count,
                        ))
                        await dup_db.commit()
                    await _bump(job_id, processed_files=1, skipped_files=1)
                    return

                if any(d.document_type == "transcript" for d in result.documents):
                    meeting.transcript_available = True
                    if meeting.status != MeetingStatus.ready:
                        meeting.status = MeetingStatus.ready
                    if any(d.end_time is not None for d in result.documents):
                        max_end = max((d.end_time or 0.0 for d in result.documents), default=0.0)
                        meeting.duration_seconds = int(max(meeting.duration_seconds or 0, max_end))

                db.add(ImportedFileResult(
                    import_job_id=job_id, filename=staged.filename, relative_path=staged.relative_path,
                    file_type=file_type, status=ImportFileStatus.success, document_id=doc_row.id,
                    meeting_id=meeting.id, chunk_count=chunk_count,
                ))
                await db.commit()
                await _bump(job_id, processed_files=1, successful_files=1)
            except Exception as exc:  # noqa: BLE001 — one file's bug must not abort the batch
                logger.exception("historical_import_file_failed", extra={"file": staged.relative_path})
                await db.rollback()
                async with SessionLocal() as err_db:
                    err_db.add(ImportedFileResult(
                        import_job_id=job_id, filename=staged.filename, relative_path=staged.relative_path,
                        file_type=file_type or "unknown", status=ImportFileStatus.failed,
                        reason=f"Unexpected error: {exc}",
                        recommended_action="Retry the import; if it keeps failing, report this file.",
                    ))
                    await err_db.commit()
                await _bump(job_id, processed_files=1, failed_files=1)


async def run_import_job(job_id: str, *, tenant_id: str, user_id: str, files: list[StagedFile]) -> None:
    async with SessionLocal() as db:
        await db.execute(
            update(HistoricalImportJob).where(HistoricalImportJob.id == job_id).values(status=ImportJobStatus.processing)
        )
        await db.commit()

    semaphore = asyncio.Semaphore(max(1, get_settings().import_max_concurrency))
    await asyncio.gather(*(_process_one(job_id, tenant_id, user_id, f, semaphore) for f in files))

    async with SessionLocal() as db:
        job = (await db.execute(select(HistoricalImportJob).where(HistoricalImportJob.id == job_id))).scalar_one()
        # "failed" is reserved for a batch where files genuinely errored out
        # and nothing usable came of it — re-importing an already-imported
        # folder (100% duplicates, 0 failures) is a successful no-op, not a
        # failure, so it lands in completed/completed_with_warnings instead.
        if job.total_files == 0 or job.successful_files == job.total_files:
            job.status = ImportJobStatus.completed
        elif job.failed_files > 0 and job.successful_files == 0:
            job.status = ImportJobStatus.failed
        else:
            job.status = ImportJobStatus.completed_with_warnings
        job.current_file = None
        await db.commit()
