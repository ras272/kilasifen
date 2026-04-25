"""Pydantic schemas for event APIs."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventCreateRequest(BaseModel):
    """Event creation payload."""

    document_id: str
    event_type: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] | None = None


class EventResponse(BaseModel):
    """Event response payload."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    emitter_id: str
    document_id: str | None
    event_type: str
    input_payload: dict[str, Any] | None
    generated_xml: str | None
    signed_xml: str | None
    sifen_request_xml: str | None
    sifen_response_raw: str | None
    status: str
    sifen_result_code: str | None
    sifen_result_message: str | None
    created_at: datetime
    updated_at: datetime
