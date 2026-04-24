"""Common API response models."""

from typing import Any

from pydantic import BaseModel


class SuccessEnvelope(BaseModel):
    """Standard success response envelope."""

    data: dict[str, Any]
    correlation_id: str


class ErrorPayload(BaseModel):
    """Standard error payload."""

    code: str
    message: str
    category: str
    correlation_id: str


class ErrorEnvelope(BaseModel):
    """Standard error response envelope."""

    error: ErrorPayload
