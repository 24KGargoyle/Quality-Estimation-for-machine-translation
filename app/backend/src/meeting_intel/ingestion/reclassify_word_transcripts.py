"""Repair classifications of locally stored Word imports.

Run from app/backend with src on PYTHONPATH:
python -m meeting_intel.ingestion.reclassify_word_transcripts
This updates database metadata; it does not rebuild the search index.
"""
import asyncio
from pathlib import Path

from sqlalchemy import select

from meeting_intel.config import get_settings
from meeting_intel.db.models import HistoricalDocument, Meeting, MeetingStatus
from meeting_intel.db.session import SessionLocal
from meeting_intel.ingestion.parsers.word_parser import WordParser


async def main() -> None:
    settings = get_settings()
    if settings.file_storage != "local":
        raise RuntimeError("This repair requires local file storage.")
    root = Path(settings.local_blob_storage_dir).resolve()
    corrected = 0
    async with SessionLocal() as db:
        rows = (await db.execute(select(HistoricalDocument).where(
            HistoricalDocument.file_type == "docx",
            HistoricalDocument.document_type == "supporting_document",
            HistoricalDocument.chunk_count > 0,
        ))).scalars().all()
        for row in rows:
            if not row.blob_path:
                continue
            path = (root / row.blob_path).resolve()
            if root not in path.parents or not path.is_file():
                continue
            parsed = WordParser().parse(
                content=path.read_bytes(), filename=row.source_file,
                relative_path=row.relative_path, tenant_id=row.tenant_id,
                meeting_id=row.meeting_id, title=row.source_file, document_id_prefix=row.id,
            )
            if not any(d.document_type == "transcript" for d in parsed.documents):
                continue
            row.document_type = "transcript"
            if row.meeting_id:
                meeting = await db.get(Meeting, row.meeting_id)
                if meeting and meeting.tenant_id == row.tenant_id:
                    meeting.transcript_available = True
                    meeting.status = MeetingStatus.ready
            corrected += 1
        await db.commit()
    print(f"Reclassified {corrected} Word transcripts.")


if __name__ == "__main__":
    asyncio.run(main())
