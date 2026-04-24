"""API error mapping helpers."""

from fastapi import Request
from fastapi.responses import JSONResponse

from kilasifen.api.schemas.common import ErrorEnvelope, ErrorPayload


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
