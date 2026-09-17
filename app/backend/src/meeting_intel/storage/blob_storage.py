"""Raw historical-import file storage. Metadata (hash, type, tenant, meeting,
import job) lives in Azure SQL/SQLite (`db.models.HistoricalDocument`) —
never the file bytes themselves, per the upgrade spec's "do not
unnecessarily store large binary files in Azure SQL" requirement (§22).

Two implementations:
  - `LocalBlobStorage` (default, `FILE_STORAGE=local`): a real, working
    on-disk store for local development/tests — not Azure Blob Storage, and
    never presented as such.
  - `AzureBlobStorage` (`FILE_STORAGE=azure_blob`): a real Azure Blob
    Storage REST client (`httpx`, no `azure-storage-blob` SDK dependency —
    consistent with the `AzureAISearchProvider` REST-over-SDK choice)
    authenticated via a container-scoped SAS URL. Inert
    (`BlobStorageNotConfiguredError`) without `AZURE_STORAGE_CONTAINER_SAS_URL`.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from meeting_intel.config import get_settings

logger = logging.getLogger("meeting_intel.storage")


class BlobStorageNotConfiguredError(RuntimeError):
    """Raised by a storage backend that requires configuration it doesn't have."""


class BlobStorage(ABC):
    @abstractmethod
    async def save(self, *, path: str, content: bytes) -> str:
        """Persist `content` at `path` (already sanitized — see
        security/file_safety.py) and return a backend-specific reference to
        store as `HistoricalDocument.blob_path`."""


class LocalBlobStorage(BlobStorage):
    def __init__(self, root: Path | None = None) -> None:
        settings = get_settings()
        self.root = root or Path(settings.local_blob_storage_dir)

    async def save(self, *, path: str, content: bytes) -> str:
        full = (self.root / path).resolve()
        if self.root.resolve() not in full.parents and full != self.root.resolve():
            raise ValueError("Resolved path escapes the storage root.")
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(content)
        return str(full.relative_to(self.root.resolve()))


class AzureBlobStorage(BlobStorage):
    def __init__(self) -> None:
        self.settings = get_settings()

    async def save(self, *, path: str, content: bytes) -> str:
        sas_url = self.settings.azure_storage_container_sas_url
        if not sas_url:
            raise BlobStorageNotConfiguredError(
                "Azure Blob Storage is not configured. Set AZURE_STORAGE_CONTAINER_SAS_URL."
            )
        base, _, query = sas_url.partition("?")
        url = f"{base.rstrip('/')}/{path}?{query}"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.put(
                    url,
                    content=content,
                    headers={"x-ms-blob-type": "BlockBlob", "Content-Type": "application/octet-stream"},
                )
            response.raise_for_status()
        except BlobStorageNotConfiguredError:
            raise
        except Exception as exc:
            logger.warning("azure_blob_upload_failed")
            raise BlobStorageNotConfiguredError(f"Azure Blob Storage upload failed: {exc}") from None
        return path


_storage: BlobStorage | None = None


def get_blob_storage() -> BlobStorage:
    global _storage
    if _storage is None:
        settings = get_settings()
        _storage = AzureBlobStorage() if settings.file_storage == "azure_blob" else LocalBlobStorage()
    return _storage
