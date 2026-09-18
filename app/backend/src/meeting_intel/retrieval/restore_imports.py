"""Rebuild missing local import chunks on demand after a process restart."""
import asyncio
from pathlib import Path

from sqlalchemy import select

from meeting_intel.config import get_settings
from meeting_intel.db.models import HistoricalDocument, Meeting

_restore_lock = asyncio.Lock()


class ImportedContentUnavailableError(RuntimeError):
    pass


async def restore_imports(db, *, tenant_id: str, meeting_ids: list[str], document_id: str | None = None) -> None:
    settings = get_settings()
    if settings.search_provider != "memory":
        return
    from meeting_intel.ingestion.historical_import import _index_documents
    from meeting_intel.ingestion.parsers import ParserFactory
    from meeting_intel.retrieval.memory_search import get_memory_provider

    async with _restore_lock:
        rows = (await db.execute(select(HistoricalDocument).where(
            HistoricalDocument.tenant_id == tenant_id,
            HistoricalDocument.meeting_id.in_(meeting_ids),
            HistoricalDocument.chunk_count > 0,
        ))).scalars().all()
        provider = get_memory_provider()
        root = Path(settings.local_blob_storage_dir).resolve()
        for row in rows:
            prefix = f"hist:{row.file_hash[:16]}"
            if document_id is not None and prefix != document_id:
                continue
            chunks = await provider.chunks_for_meeting(tenant_id=tenant_id, meeting_id=row.meeting_id)
            if sum(c.id.startswith(prefix + ":") for c in chunks) >= row.chunk_count:
                continue
            if settings.file_storage != "local" or not row.blob_path:
                raise ImportedContentUnavailableError("Imported content needs reindexing, but its local source file is unavailable.")
            path = (root / row.blob_path).resolve()
            if root not in path.parents or not path.is_file():
                raise ImportedContentUnavailableError("An imported source file is missing. Restore the file before asking questions.")
            meeting = await db.get(Meeting, row.meeting_id)
            parser = ParserFactory.get_parser(row.file_type)
            result = await asyncio.to_thread(
                parser.parse, content=path.read_bytes(), filename=row.source_file,
                relative_path=row.relative_path, tenant_id=tenant_id, meeting_id=row.meeting_id,
                title=meeting.title, document_id_prefix=prefix,
            )
            await _index_documents(result.documents, tenant_id=tenant_id, meeting=meeting,
                                   source_label="historical_import", document_id_prefix=prefix)
