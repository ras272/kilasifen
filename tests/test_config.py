import pytest
from pydantic import ValidationError

from kilasifen.config import Settings

VALID_KEY = "4fV1_r04jQs6C1UNq9qS4RuCs1oQcWzER8GqW04A1lE="


def test_development_keeps_safe_local_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.sifen_environment == "test"
    assert settings.readiness_requires_workers is False


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"api_keys": []}, "bootstrap API key"),
        ({"encryption_key": None}, "ENCRYPTION_KEY"),
        ({"database_url": "sqlite:///unsafe.db"}, "PostgreSQL"),
        (
            {"database_url": "postgresql+psycopg://user:pass@localhost/db"},
            "PostgreSQL cannot use localhost",
        ),
        ({"redis_url": "redis://localhost:6379/0"}, "Redis cannot use localhost"),
        (
            {"request_limits_enabled": False},
            "request limits cannot be disabled",
        ),
    ],
)
def test_staging_rejects_incomplete_or_local_configuration(
    override: dict[str, object],
    message: str,
) -> None:
    values = {
        "environment": "staging",
        "api_keys": ["bootstrap-secret"],
        "encryption_key": VALID_KEY,
        "database_url": "postgresql+psycopg://user:pass@postgres.internal/db",
        "redis_url": "redis://redis.internal:6379/0",
        "sifen_environment": "test",
        "_env_file": None,
    }
    values.update(override)

    with pytest.raises(ValidationError, match=message):
        Settings(**values)


def test_staging_accepts_only_test_sifen_with_remote_dependencies() -> None:
    settings = Settings(
        environment="staging",
        api_keys=["bootstrap-secret"],
        encryption_key=VALID_KEY,
        database_url="postgresql+psycopg://user:pass@postgres.internal/db",
        redis_url="rediss://redis.internal:6379/0",
        sifen_environment="test",
        _env_file=None,
    )

    assert settings.readiness_requires_workers is True


def test_production_requires_explicit_enablement() -> None:
    with pytest.raises(ValidationError, match="enable_production=true"):
        Settings(
            environment="production",
            api_keys=["bootstrap-secret"],
            encryption_key=VALID_KEY,
            database_url="postgresql+psycopg://user:pass@postgres.internal/db",
            redis_url="rediss://redis.internal:6379/0",
            sifen_environment="production",
            enable_production=False,
            _env_file=None,
        )


def test_trusted_proxy_ranges_must_be_valid_cidrs() -> None:
    with pytest.raises(ValidationError, match="does not appear"):
        Settings(trusted_proxy_cidrs=["not-a-network"], _env_file=None)
