"""Runtime configuration for the Kila SIFEN platform."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
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
    environment: Literal["development", "test", "staging", "production"] = (
        "development"
    )
    log_level: str = "INFO"
    api_keys: list[str] = Field(default_factory=list)
    database_url: str = Field(
        default="sqlite:///./kilasifen.db",
    )
    redis_url: str = Field(default="redis://localhost:6379/0")
    encryption_key: str | None = None
    sifen_environment: Literal["test", "production"] = "test"
    enable_production: bool = False
    max_pfx_upload_bytes: int = Field(default=2 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)
    sentry_dsn: str | None = None
    sentry_environment: str = "development"
    sentry_release: str | None = None
    sentry_traces_sample_rate: float = 0.0
    document_auto_enqueue: bool = False
    document_publish_webhooks: bool = False

    @model_validator(mode="after")
    def validate_sifen_deployment_boundary(self) -> "Settings":
        if self.environment == "staging" and self.sifen_environment != "test":
            raise ValueError("staging is restricted to the SIFEN test environment")
        if self.sifen_environment == "production":
            if self.environment != "production" or not self.enable_production:
                raise ValueError(
                    "SIFEN production requires environment=production and "
                    "enable_production=true"
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
