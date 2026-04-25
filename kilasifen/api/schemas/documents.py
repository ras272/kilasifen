"""Pydantic schemas for document APIs."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentCreateRequest(BaseModel):
    """Document creation payload."""

    external_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)
    document_type: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] | None = None


class DocumentResponse(BaseModel):
    """Document response payload."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    emitter_id: str
    external_id: str | None
    idempotency_key: str | None
    document_type: str
    payload_snapshot: dict[str, Any] | None
    generated_xml: str | None
    signed_xml: str | None
    sifen_request_xml: str | None
    sifen_response_raw: str | None
    cdc: str | None
    internal_status: str
    sifen_status: str | None
    sifen_result_code: str | None
    sifen_result_message: str | None
    created_at: datetime
    updated_at: datetime
