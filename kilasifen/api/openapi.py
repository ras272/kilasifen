"""OpenAPI details that FastAPI cannot declare route by route.

- Every response carries ``X-Correlation-ID`` (the correlation middleware and
  the unhandled-error handler add it), so every response declares it.
- The scope an operation requires is read from the scope dependency the
  endpoint really declares, so the reference cannot drift from the
  enforcement.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from kilasifen.api.deps import (
    get_admin_principal,
    get_api_key_principal,
    require_emitter_create,
    require_emitter_read,
    require_emitter_write,
    require_fiscal_write,
    require_secrets_write,
    require_tenant_read,
)
from kilasifen.api.errors import CORRELATION_ID_HEADER
from kilasifen.security import (
    EMITTERS_CREATE_SCOPE,
    FISCAL_WRITE_SCOPE,
    PLATFORM_ADMIN_SCOPE,
    SECRETS_WRITE_SCOPE,
    TENANT_READ_SCOPE,
    TENANT_WRITE_SCOPE,
)

_CORRELATION_HEADER = {
    "description": (
        "Identificador de la solicitud, igual a `correlation_id` del body. "
        "Conservalo en los logs del ERP y en los tickets de soporte."
    ),
    "schema": {"type": "string"},
}

_SCOPE_BY_DEPENDENCY: dict[Callable[..., Any], str] = {
    get_admin_principal: PLATFORM_ADMIN_SCOPE,
    require_emitter_create: EMITTERS_CREATE_SCOPE,
    require_tenant_read: TENANT_READ_SCOPE,
    require_emitter_read: TENANT_READ_SCOPE,
    require_emitter_write: TENANT_WRITE_SCOPE,
    require_fiscal_write: FISCAL_WRITE_SCOPE,
    require_secrets_write: SECRETS_WRITE_SCOPE,
}


def install_openapi_extensions(
    app: FastAPI, *, api_prefix: str, routers: Iterable[APIRouter]
) -> None:
    """Extend the schema FastAPI generates, every time it regenerates it.

    ``routers`` are the routers included under ``api_prefix``; their own
    routes are read because they keep the endpoint dependencies as declared.
    """

    routes = [
        (f"{api_prefix}{route.path_format}", route)
        for router in routers
        for route in router.routes
        if isinstance(route, APIRoute) and route.include_in_schema
    ]
    generate = app.openapi
    extended: dict[str, Any] | None = None

    def openapi() -> dict[str, Any]:
        nonlocal extended
        schema = generate()
        if schema is not extended:
            _declare_correlation_header(schema)
            _document_required_scopes(schema, routes)
            extended = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]


def _declare_correlation_header(schema: dict[str, Any]) -> None:
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            for response in operation.get("responses", {}).values():
                response.setdefault("headers", {})[CORRELATION_ID_HEADER] = dict(
                    _CORRELATION_HEADER
                )


def _document_required_scopes(
    schema: dict[str, Any], routes: list[tuple[str, APIRoute]]
) -> None:
    for path, route in routes:
        note = _scope_note(route.dependant)
        if note is None:
            continue
        for method in route.methods:
            operation = schema["paths"][path][method.lower()]
            description = operation.get("description")
            operation["description"] = (
                f"{description}\n\n{note}" if description else note
            )


def _scope_note(dependant: Dependant) -> str | None:
    calls = set(_dependency_calls(dependant))
    scopes = sorted(
        _SCOPE_BY_DEPENDENCY[call] for call in calls & _SCOPE_BY_DEPENDENCY.keys()
    )
    if scopes == [PLATFORM_ADMIN_SCOPE]:
        return f"**Scope:** `{PLATFORM_ADMIN_SCOPE}`."
    if scopes:
        listed = " y ".join(f"`{scope}`" for scope in scopes)
        return f"**Scope:** {listed} (también `{PLATFORM_ADMIN_SCOPE}`)."
    if get_api_key_principal in calls:
        return "**Scope:** cualquier API key válida."
    return None


def _dependency_calls(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    for dependency in dependant.dependencies:
        if dependency.call is not None:
            yield dependency.call
        yield from _dependency_calls(dependency)
