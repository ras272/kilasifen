"""Shared API dependencies."""

from collections.abc import Callable

from fastapi import Header

from kilasifen.security import ApiKeyPrincipal, validate_api_key


def get_api_key_principal(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> ApiKeyPrincipal:
    """Resolve and validate the caller API key."""

    return validate_api_key(x_api_key)


RequireApiKey = Callable[..., ApiKeyPrincipal]
