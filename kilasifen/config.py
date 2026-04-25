"""Runtime configuration for the Kila SIFEN platform."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven platform settings."""

    model_config = SettingsConfigDict(
        env_prefix="KILA_SIFEN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_title: str = "Kila SIFEN"
    api_version: str = "v1"
    log_level: str = "INFO"
    api_keys: list[str] = Field(default_factory=list)
    database_url: str = Field(
        default="sqlite:///./kilasifen.db",
    )
    redis_url: str = Field(default="redis://localhost:6379/0")
    encryption_key: str | None = None
    sifen_environment: Literal["test", "production"] = "test"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
