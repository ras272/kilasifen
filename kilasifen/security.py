"""Security helpers for the Kila SIFEN platform."""

from dataclasses import dataclass

from kilasifen.api.errors import ApiError
from kilasifen.config import get_settings


@dataclass(frozen=True)
class ApiKeyPrincipal:
    """Authenticated API key identity."""

    key: str


def validate_api_key(api_key: str | None) -> ApiKeyPrincipal:
    """Validate an incoming API key against configured keys."""

    if api_key is None:
        raise ApiError(
            status_code=401,
            code="auth.missing_api_key",
            message="API key is required.",
            category="authentication",
        )

    settings = get_settings()
    if api_key not in settings.api_keys:
        raise ApiError(
            status_code=401,
            code="auth.invalid_api_key",
            message="API key is invalid.",
            category="authentication",
        )

    return ApiKeyPrincipal(key=api_key)
