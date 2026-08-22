"""Runtime configuration for the Kila SIFEN platform."""

import base64
from functools import lru_cache
from ipaddress import ip_network
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
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
    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    api_keys: list[str] = Field(default_factory=list)
    database_url: str = Field(
        default="sqlite:///./kilasifen.db",
    )
    redis_url: str = Field(default="redis://localhost:6379/0")
    encryption_key: str | None = None
    sifen_environment: Literal["test", "production"] = "test"
    enable_production: bool = False
    max_pfx_upload_bytes: int = Field(
        default=2 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024
    )
    max_json_request_body_bytes: int = Field(
        default=1024 * 1024,
        ge=1024,
        le=10 * 1024 * 1024,
    )
    multipart_body_overhead_bytes: int = Field(
        default=64 * 1024,
        ge=4096,
        le=1024 * 1024,
    )
    request_limits_enabled: bool = True
    pre_auth_rate_limit_requests: int = Field(default=600, ge=1, le=1_000_000)
    pre_auth_max_concurrent_requests: int = Field(default=32, ge=1, le=10_000)
    trusted_proxy_cidrs: list[str] = Field(default_factory=list)
    rate_limit_requests: int = Field(default=120, ge=1, le=100_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3_600)
    max_concurrent_requests: int = Field(default=8, ge=1, le=1_000)
    request_lease_seconds: int = Field(default=120, ge=10, le=3_600)
    readiness_cache_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    sentry_dsn: str | None = None
    sentry_environment: str = "development"
    sentry_release: str | None = None
    sentry_traces_sample_rate: float = 0.0
    document_auto_enqueue: bool = False
    document_publish_webhooks: bool = False

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, values: list[str]) -> list[str]:
        """Reject invalid proxy ranges instead of silently trusting bad config."""

        for value in values:
            ip_network(value, strict=False)
        return values

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
        if self.environment in {"staging", "production"}:
            self._validate_public_runtime()
        return self

    @property
    def readiness_requires_workers(self) -> bool:
        """Require both queues to have workers outside local/test runtimes."""

        return self.environment in {"staging", "production"}

    def _validate_public_runtime(self) -> None:
        if not self.api_keys:
            raise ValueError("at least one bootstrap API key is required")
        if not self.encryption_key or not _is_fernet_key(self.encryption_key):
            raise ValueError("a valid KILA_SIFEN_ENCRYPTION_KEY is required")
        if not self.request_limits_enabled:
            raise ValueError("request limits cannot be disabled in staging/production")

        database = urlparse(self.database_url)
        if not database.scheme.startswith("postgresql"):
            raise ValueError("staging/production requires PostgreSQL")
        if _is_local_host(database.hostname):
            raise ValueError("staging/production PostgreSQL cannot use localhost")

        redis = urlparse(self.redis_url)
        if redis.scheme not in {"redis", "rediss"}:
            raise ValueError("staging/production requires Redis")
        if _is_local_host(redis.hostname):
            raise ValueError("staging/production Redis cannot use localhost")


def _is_fernet_key(value: str) -> bool:
    try:
        return len(base64.urlsafe_b64decode(value.encode("ascii"))) == 32
    except (ValueError, UnicodeEncodeError):
        return False


def _is_local_host(hostname: str | None) -> bool:
    return hostname is None or hostname.lower() in {"localhost", "127.0.0.1", "::1"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
