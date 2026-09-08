"""Application configuration.

All secrets and environment-specific values come from environment variables /
a local `.env` file (never committed — see `.env.example`). Nothing here is
hardcoded.
"""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Core ---
    app_env: Literal["local", "staging", "production"] = "local"
    database_url: str = "postgresql+asyncpg://meeting_intel:meeting_intel@localhost:5432/meeting_intel"
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
    anthropic_api_key: str | None = None
    llm_model: str = "claude-sonnet-5"

    # --- Embeddings ---
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # --- Retrieval ---
    retrieval_top_k: int = 8
    retrieval_min_score: float = 0.15

    # --- CORS ---
    cors_origins: str = "http://localhost:3000"

    @property
    def graph_configured(self) -> bool:
        return bool(self.ms_tenant_id and self.ms_client_id and self.ms_client_secret)

    @property
    def llm_configured(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
