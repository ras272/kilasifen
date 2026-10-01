"""API error mapping helpers.

Every error the API produces, including framework errors (request validation,
unknown routes, unsupported methods) and unhandled exceptions, is rendered with
the same :class:`ErrorEnvelope` so clients can rely on one contract.
"""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from kilasifen.api.schemas.common import ErrorEnvelope, ErrorPayload
from kilasifen.domain.common.errors import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    UnprocessableEntityError,
)

logger = logging.getLogger(__name__)

CORRELATION_ID_HEADER = "X-Correlation-ID"

_ERROR_DESCRIPTIONS: dict[int, str] = {
    401: "Missing or invalid API key.",
    403: "The credential lacks the required scope.",
    404: "Resource not found or owned by another tenant.",
    409: "Resource conflict or state that does not allow the operation.",
    413: "Request body exceeds the configured size limit; see `details.max_bytes`.",
    422: "Request validation failed; the request was not processed.",
    429: "Request limit exceeded; retry after `details.retry_after_seconds`.",
    503: "A dependency is temporarily unavailable; retry with backoff.",
}

# Headers that accompany an error status in every response that declares it.
_ERROR_HEADERS: dict[int, dict[str, dict[str, Any]]] = {
    429: {
        "Retry-After": {
            "description": "Seconds to wait before retrying the request.",
            "schema": {"type": "integer"},
        }
    },
}

# Framework HTTP errors mapped to stable codes. Unknown statuses fall back to
# ``http.<status>`` so the envelope is always present.
_HTTP_ERRORS: dict[int, tuple[str, str, str]] = {
    400: ("request.bad_request", "invalid_request", "Request is malformed."),
    404: ("request.route_not_found", "not_found", "Route was not found."),
    405: (
        "request.method_not_allowed",
        "invalid_request",
        "HTTP method is not allowed for this route.",
    ),
    406: (
        "request.not_acceptable",
        "invalid_request",
        "Requested media type is not available.",
    ),
    413: (
        "request.body_too_large",
        "validation",
        "Request body exceeds the configured size limit.",
    ),
    415: (
        "request.unsupported_media_type",
        "invalid_request",
        "Request media type is not supported.",
    ),
}


class ApiError(Exception):
    """Raised when the API should return a structured error response."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        category: str,
        details: dict | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.category = category
        self.details = details
        self.headers = headers


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """Build OpenAPI ``responses`` declaring the error envelope per status."""

    return {
        status_code: {
            "model": ErrorEnvelope,
            "description": _ERROR_DESCRIPTIONS[status_code],
            **(
                {"headers": _ERROR_HEADERS[status_code]}
                if status_code in _ERROR_HEADERS
                else {}
            ),
        }
        for status_code in status_codes
    }


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    """Serialize structured API errors."""

    correlation_id = getattr(request.state, "correlation_id", "unknown")
    payload = ErrorEnvelope(
        error=ErrorPayload(
            code=exc.code,
            message=exc.message,
            category=exc.category,
            correlation_id=correlation_id,
            details=exc.details,
        )
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=payload.model_dump(),
        headers=exc.headers,
    )


async def request_validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Serialize FastAPI request validation errors without echoing inputs."""

    return await api_error_handler(
        request,
        ApiError(
            status_code=422,
            code="request.validation_failed",
            message="Request validation failed.",
            category="validation",
            details={"errors": _validation_errors(exc)},
        ),
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Serialize framework HTTP errors such as unknown routes or methods."""

    code, category, message = _http_error(exc.status_code)
    return await api_error_handler(
        request,
        ApiError(
            status_code=exc.status_code,
            code=code,
            message=message,
            category=category,
            headers=dict(exc.headers) if exc.headers else None,
        ),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Serialize unexpected failures without leaking internal details.

    Starlette invokes this handler outside the correlation middleware, so the
    correlation header is added here explicitly. The exception is re-raised by
    Starlette afterwards, which lets the server log the full traceback.
    """

    correlation_id = getattr(request.state, "correlation_id", "unknown")
    logger.error(
        "http.unhandled_exception",
        extra={
            "correlation_id": correlation_id,
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )
    response = await api_error_handler(
        request,
        ApiError(
            status_code=500,
            code="server.internal_error",
            message="Unexpected server error. Retry later or contact support.",
            category="internal",
        ),
    )
    response.headers[CORRELATION_ID_HEADER] = correlation_id
    return response


async def not_found_error_handler(
    request: Request,
    exc: NotFoundError,
) -> JSONResponse:
    """Serialize structured not-found errors."""

    return await api_error_handler(
        request,
        ApiError(
            status_code=404,
            code=str(exc),
            message="Resource was not found.",
            category="not_found",
        ),
    )


async def conflict_error_handler(
    request: Request,
    exc: ConflictError,
) -> JSONResponse:
    """Serialize structured conflict errors."""

    return await api_error_handler(
        request,
        ApiError(
            status_code=409,
            code=str(exc),
            message="Resource conflict.",
            category="conflict",
            details=getattr(exc, "details", None),
        ),
    )


async def service_unavailable_error_handler(
    request: Request,
    exc: ServiceUnavailableError,
) -> JSONResponse:
    """Serialize structured service-unavailable errors."""

    return await api_error_handler(
        request,
        ApiError(
            status_code=503,
            code=str(exc),
            message="Service temporarily unavailable. Retry later.",
            category="service_unavailable",
        ),
    )


async def unprocessable_entity_error_handler(
    request: Request,
    exc: UnprocessableEntityError,
) -> JSONResponse:
    """Serialize structured unprocessable-entity errors."""

    return await api_error_handler(
        request,
        ApiError(
            status_code=422,
            code=str(exc),
            message="Request validation failed.",
            category="validation",
            details=getattr(exc, "details", None),
        ),
    )


def _validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Keep location, message and type; never echo submitted values back."""

    return [
        {
            "loc": list(error.get("loc", ())),
            "message": str(error.get("msg", "")),
            "type": str(error.get("type", "")),
        }
        for error in exc.errors()
    ]


def _http_error(status_code: int) -> tuple[str, str, str]:
    known = _HTTP_ERRORS.get(status_code)
    if known is not None:
        return known
    try:
        phrase = HTTPStatus(status_code).phrase
    except ValueError:
        phrase = "HTTP error"
    category = "internal" if status_code >= 500 else "invalid_request"
    return f"http.{status_code}", category, f"{phrase}."
