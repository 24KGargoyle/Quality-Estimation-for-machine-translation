"""Application configuration.

All secrets and environment-specific values come from environment variables /
a local `.env` file (never committed — see `.env.example`). Nothing here is
hardcoded.

PostgreSQL-free refactor: the relational store is SQLite for local
development/tests (real, working, zero external dependency) or Azure SQL in
production (`AZURE_SQL_CONNECTION_STRING`, an async-capable driver required —
see docs/AZURE_SETUP.md); vector/keyword/hybrid transcript search is Azure AI
Search (`SEARCH_PROVIDER=azure_search`) or, for local dev/tests, a real
in-process implementation (`SEARCH_PROVIDER=memory`, the default) that is
never presented as Azure AI Search. See docs/MIGRATION_FROM_POSTGRES.md.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


def ensure_sqlite_parent_dir(url: str) -> None:
    """SQLite needs its parent directory (e.g. ./data/) to exist before it
    will create the database file. Safe to call for any URL — a no-op for
    non-SQLite (e.g. Azure SQL) connection strings."""
    if not url.startswith("sqlite"):
        return
    path = Path(url.split("///", 1)[-1])
    if path.suffix:
        path.parent.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Core ---
    app_env: Literal["local", "staging", "production"] = "local"
    # Real, working default: SQLite via the async aiosqlite driver — no
    # external database server required for local development or tests.
    database_url: str = "sqlite+aiosqlite:///./data/meeting_intel.db"
    # Production target. When set, takes precedence over `database_url` (see
    # `resolved_database_url`). Must use an async-capable SQLAlchemy driver —
    # see docs/AZURE_SETUP.md for exact connection string requirements and
    # the documented sync fallback if your ODBC driver stack has no async
    # support.
    azure_sql_connection_string: str | None = None
    secret_key: str = "CHANGE_ME_DEV_ONLY_NOT_FOR_PRODUCTION"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 12

    # --- Auth provider ---
    # "entra": real Microsoft Entra ID OIDC (requires the ms_* settings below).
    # "dev": local username/password style login for development/testing only.
    #        Refuses to start in app_env=production.
    auth_provider: Literal["entra", "dev"] = "dev"

    # --- Microsoft Entra ID / Graph (required when auth_provider=entra) ---
    ms_tenant_id: str | None = None
    ms_client_id: str | None = None
    ms_client_secret: str | None = None
    ms_redirect_uri: str | None = None
    graph_scopes: str = "OnlineMeetings.Read,OnlineMeetingTranscript.Read.All,Chat.ReadWrite,ChannelMessage.Send"

    # --- LLM ---
    # "anthropic" (default, working today) or "azure_openai" (real, inert
    # without AZURE_OPENAI_* credentials — see providers.py).
    llm_provider: Literal["anthropic", "azure_openai"] = "anthropic"
    anthropic_api_key: str | None = None
    llm_model: str = "claude-sonnet-5"
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_chat_deployment: str | None = None
    azure_openai_embedding_deployment: str | None = None
    # Never inferred from the deployment name (an alias) — must match the
    # actual deployed embedding model's real output size.
    azure_openai_embedding_dimensions: int | None = None

    # --- Embeddings ---
    # "local" (default, working today — sentence-transformers, no API key
    # required) or "azure_openai" (real, inert without credentials).
    embedding_provider: Literal["local", "azure_openai"] = "local"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # --- Search (RAG) ---
    # "memory" (default): a real, working, in-process hybrid search
    #   implementation for local development and tests — NOT Azure AI Search,
    #   never presented as such (see retrieval/memory_search.py).
    # "azure_search": real Azure AI Search REST client (see
    #   retrieval/azure_search.py); inert without the AZURE_SEARCH_* settings.
    search_provider: Literal["memory", "azure_search"] = "memory"
    azure_search_endpoint: str | None = None
    azure_search_api_key: str | None = None
    azure_search_index: str = "transcript-chunks"
    azure_search_semantic_config: str = "default"

    # --- Retrieval ---
    retrieval_top_k: int = 8
    retrieval_min_score: float = 0.15

    # --- Historical Meeting Data Import ---
    # "local" (default): a real, working on-disk store for dev/tests — NOT
    #   Azure Blob Storage. "azure_blob": a real Azure Blob Storage REST
    #   client, inert without AZURE_STORAGE_CONTAINER_SAS_URL.
    file_storage: Literal["local", "azure_blob"] = "local"
    local_blob_storage_dir: str = "./data/historical_blobs"
    azure_storage_container_sas_url: str | None = None
    import_max_concurrency: int = 4

    # --- CORS ---
    cors_origins: str = "http://localhost:3000"

    @property
    def resolved_database_url(self) -> str:
        """AZURE_SQL_CONNECTION_STRING, when set, always wins over the
        SQLite dev default — this is the single place callers should read
        the active database URL from."""
        return self.azure_sql_connection_string or self.database_url

    @property
    def graph_configured(self) -> bool:
        return bool(self.ms_tenant_id and self.ms_client_id and self.ms_client_secret)

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "azure_openai":
            return bool(self.azure_openai_endpoint and self.azure_openai_api_key and self.azure_openai_chat_deployment)
        return bool(self.anthropic_api_key)

    @property
    def embedding_configured(self) -> bool:
        if self.embedding_provider == "azure_openai":
            return bool(
                self.azure_openai_endpoint
                and self.azure_openai_api_key
                and self.azure_openai_embedding_deployment
                and self.azure_openai_embedding_dimensions
            )
        return True  # local sentence-transformers needs no credentials

    @property
    def search_configured(self) -> bool:
        return bool(self.azure_search_endpoint and self.azure_search_api_key and self.azure_search_index)


@lru_cache
def get_settings() -> Settings:
    return Settings()
