"""Application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from TELEFIX-prefixed environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="TELEFIX_",
        extra="ignore",
    )

    app_name: str = "Telefix Agent Evaluation"
    environment: str = "local"
    rag_backend: Literal["local", "qdrant"] = "local"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "synthetic_broadband_manuals"
    qdrant_api_key: str | None = None
    rag_top_k: int = 3
    state_backend: Literal["memory", "redis"] = "memory"
    redis_url: str = "redis://localhost:6379/0"


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings object."""

    return Settings()
