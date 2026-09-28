"""Historical Meeting Data Import API (§18-§21 of the upgrade spec).

A batch upload is processed as a background job rather than inside one
blocking HTTP request — see ingestion/historical_import.py for why (no
separate worker/queue process in this environment) and its documented
limitation (an in-flight job is lost on a process restart).

Frontend convention: each `UploadFile`'s `filename` carries the file's
*relative path within the selected folder* (the frontend sets it via
`formData.append("files", file, file.webkitRelativePath || file.name)`),
not just its basename — this endpoint recovers both the folder-relative
path and the plain filename from that one field. See
docs/HISTORICAL_IMPORT.md.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from meeting_intel.api.schemas import ImportedFileResultSchema, ImportJobResults, ImportJobSummary
from meeting_intel.auth.deps import RequestContext, get_current_context
from meeting_intel.db.models import ImportedFileResult
from meeting_intel.db.session import get_db
from meeting_intel.ingestion.historical_import import StagedFile, create_import_job, run_import_job
from meeting_intel.security.authz import audit, get_authorized_import_job
from meeting_intel.security.file_safety import (
    MAX_FILE_SIZE_BYTES,
    MAX_FILES_PER_IMPORT,
    MAX_TOTAL_IMPORT_BYTES,
    UnsafePathError,
    sanitize_filename,
    sanitize_relative_path,
)

router = APIRouter(prefix="/api/historical-imports", tags=["historical-imports"])

# Keeps a strong reference to in-flight background jobs so they aren't
# garbage-collected mid-run, and surfaces an unexpected crash in the task
# itself (as opposed to a per-file error, which historical_import.py already
# catches and records) to the server log instead of it vanishing silently.
_background_jobs: set[asyncio.Task] = set()


@router.delete("/{job_id}")
async def delete_import_job(
    job_id: str, ctx: RequestContext = Depends(get_current_context), db: AsyncSession = Depends(get_db),
) -> dict:
    from meeting_intel.db.models import HistoricalDocument, HistoricalImportJob, ImportJobStatus, Meeting, UserRole
    from meeting_intel.retrieval.hybrid_search import get_search_provider
    from meeting_intel.storage.blob_storage import get_blob_storage

    job = await get_authorized_import_job(db, user=ctx.user, job_id=job_id)
    if job.created_by != ctx.user.id and ctx.user.role != UserRole.admin:
        raise HTTPException(403, "Only the uploader or a tenant administrator can delete this import.")
    active = (await db.execute(select(HistoricalImportJob.id).where(
        HistoricalImportJob.tenant_id == ctx.tenant_id,
        HistoricalImportJob.status.in_([ImportJobStatus.queued, ImportJobStatus.processing]),
    ))).first()
    if active:
        raise HTTPException(409, "Wait for running imports to finish before deleting.")
    documents = (await db.execute(select(HistoricalDocument).where(
        HistoricalDocument.tenant_id == ctx.tenant_id, HistoricalDocument.import_job_id == job.id,
    ))).scalars().all()
    try:
        for document in documents:
            if document.meeting_id:
                await get_search_provider().delete_document(
                    tenant_id=ctx.tenant_id, meeting_id=document.meeting_id,
                    document_id=f"hist:{document.file_hash[:16]}",
                )
            if document.blob_path:
                await get_blob_storage().delete(path=document.blob_path)
    except Exception:
        # Keep metadata/history so a failed external deletion can be retried.
        raise HTTPException(503, "Could not finish deleting stored files or search entries. Please retry.") from None
    for document in documents:
        from meeting_intel.retrieval.local_index_cache import cache_path
        cache_path(ctx.tenant_id, document.meeting_id, f'hist:{document.file_hash[:16]}').unlink(missing_ok=True)
        await db.delete(document)
    await db.flush()
    for meeting_id in {document.meeting_id for document in documents if document.meeting_id}:
        meeting = await db.get(Meeting, meeting_id)
        if meeting and meeting.is_historical:
            remaining_transcript = (await db.execute(select(HistoricalDocument.id).where(
                HistoricalDocument.tenant_id == ctx.tenant_id,
                HistoricalDocument.meeting_id == meeting_id,
                HistoricalDocument.document_type == "transcript",
            ))).first()
            meeting.transcript_available = remaining_transcript is not None
    await db.execute(delete(ImportedFileResult).where(ImportedFileResult.import_job_id == job.id))
    await db.delete(job)
    await audit(db, tenant_id=ctx.tenant_id, user_id=ctx.user.id, action="historical_import.delete",
                resource_type="import_job", resource_id=job_id, request_id=ctx.request_id,
                extra={"deleted_documents": len(documents)})
    await db.commit()
    return {"deleted_documents": len(documents)}


@router.get('/capabilities')
async def import_capabilities(ctx: RequestContext = Depends(get_current_context)) -> dict:
    from meeting_intel.ingestion.capabilities import capabilities
    return capabilities()


def _launch(job_id: str, *, tenant_id: str, user_id: str, files: list[StagedFile]) -> None:
    task = asyncio.create_task(run_import_job(job_id, tenant_id=tenant_id, user_id=user_id, files=files))
    _background_jobs.add(task)
    task.add_done_callback(_background_jobs.discard)


@router.post("", response_model=ImportJobSummary)
async def create_historical_import(
    files: list[UploadFile] = File(...),
    ctx: RequestContext = Depends(get_current_context),
    db: AsyncSession = Depends(get_db),
) -> ImportJobSummary:
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No files provided")
    if len(files) > MAX_FILES_PER_IMPORT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Too many files in one import (max {MAX_FILES_PER_IMPORT})")

    staged: list[StagedFile] = []
    total_bytes = 0
    for f in files:
        from meeting_intel.ingestion.capabilities import file_limit
        limit = file_limit(f.filename or '')
        content = await f.read(limit + 1)
        if len(content) > limit:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"'{f.filename}' exceeds the {limit // (1024 * 1024)} MB per-file limit",
            )
        total_bytes += len(content)
        if total_bytes > MAX_TOTAL_IMPORT_BYTES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Total import size exceeds the batch limit")

        raw_path = f.filename or "unnamed"
        try:
            relative_path = sanitize_relative_path(raw_path)
            filename = sanitize_filename(raw_path)
        except UnsafePathError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unsafe file path '{raw_path}': {exc}") from exc
        if filename.lower().endswith('.zip'):
            from meeting_intel.ingestion.archives import expand_zip
            try:
                expanded = await asyncio.to_thread(expand_zip, content, relative_path)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            if any(len(item.content) > file_limit(item.filename) for item in expanded):
                raise HTTPException(400, 'An archived file exceeds its per-file limit.')
            total_bytes += sum(len(item.content) for item in expanded)
            staged.extend(expanded)
        else:
            staged.append(StagedFile(filename=filename, relative_path=relative_path, content=content))
        if len(staged) > MAX_FILES_PER_IMPORT or total_bytes > MAX_TOTAL_IMPORT_BYTES:
            raise HTTPException(400, 'Expanded import exceeds the file count or batch size limit.')

    job = await create_import_job(db, tenant_id=ctx.tenant_id, user_id=ctx.user.id, total_files=len(staged))
    await audit(
        db, tenant_id=ctx.tenant_id, user_id=ctx.user.id, action="historical_import.create",
        resource_type="import_job", resource_id=job.id, request_id=ctx.request_id,
        extra={"total_files": len(staged)},
    )
    await db.commit()

    _launch(job.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id, files=staged)

    return ImportJobSummary(
        id=job.id, status=job.status.value, total_files=job.total_files, processed_files=0,
        successful_files=0, skipped_files=0, failed_files=0, current_file=None,
        created_at=job.created_at, created_by=ctx.user.display_name,
    )


@router.get("", response_model=list[ImportJobSummary])
async def list_import_history(
    ctx: RequestContext = Depends(get_current_context), db: AsyncSession = Depends(get_db)
) -> list[ImportJobSummary]:
    from meeting_intel.db.models import HistoricalImportJob, User

    rows = (
        await db.execute(
            select(HistoricalImportJob, User.display_name)
            .join(User, User.id == HistoricalImportJob.created_by, isouter=True)
            .where(HistoricalImportJob.tenant_id == ctx.tenant_id)
            .order_by(HistoricalImportJob.created_at.desc())
        )
    ).all()
    return [
        ImportJobSummary(
            id=job.id, status=job.status.value, total_files=job.total_files, processed_files=job.processed_files,
            successful_files=job.successful_files, skipped_files=job.skipped_files, failed_files=job.failed_files,
            current_file=job.current_file, created_at=job.created_at, created_by=display_name or "Unknown",
        )
        for job, display_name in rows
    ]


@router.get("/{job_id}", response_model=ImportJobSummary)
async def get_import_job(
    job_id: str, ctx: RequestContext = Depends(get_current_context), db: AsyncSession = Depends(get_db)
) -> ImportJobSummary:
    job = await get_authorized_import_job(db, user=ctx.user, job_id=job_id)
    return ImportJobSummary(
        id=job.id, status=job.status.value, total_files=job.total_files, processed_files=job.processed_files,
        successful_files=job.successful_files, skipped_files=job.skipped_files, failed_files=job.failed_files,
        current_file=job.current_file, created_at=job.created_at, created_by=ctx.user.display_name,
    )


@router.get("/{job_id}/results", response_model=ImportJobResults)
async def get_import_job_results(
    job_id: str, ctx: RequestContext = Depends(get_current_context), db: AsyncSession = Depends(get_db)
) -> ImportJobResults:
    job = await get_authorized_import_job(db, user=ctx.user, job_id=job_id)
    rows = (
        await db.execute(
            select(ImportedFileResult)
            .where(ImportedFileResult.import_job_id == job.id)
            .order_by(ImportedFileResult.created_at)
        )
    ).scalars().all()
    return ImportJobResults(
        job=ImportJobSummary(
            id=job.id, status=job.status.value, total_files=job.total_files, processed_files=job.processed_files,
            successful_files=job.successful_files, skipped_files=job.skipped_files, failed_files=job.failed_files,
            current_file=job.current_file, created_at=job.created_at, created_by=ctx.user.display_name,
        ),
        results=[ImportedFileResultSchema.model_validate(r) for r in rows],
    )
