"""API error mapping helpers."""

from fastapi import Request
from fastapi.responses import JSONResponse

from kilasifen.api.schemas.common import ErrorEnvelope, ErrorPayload
from kilasifen.domain.common.errors import ConflictError, NotFoundError, ServiceUnavailableError


class ApiError(Exception):
    """Raised when the API should return a structured error response."""

    def __init__(self, *, status_code: int, code: str, message: str, category: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.category = category


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    """Serialize structured API errors."""

    correlation_id = getattr(request.state, "correlation_id", "unknown")
    payload = ErrorEnvelope(
        error=ErrorPayload(
            code=exc.code,
            message=exc.message,
            category=exc.category,
            correlation_id=correlation_id,
        )
    )
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


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
