"""Pydantic schemas for emitter APIs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EmitterCreateRequest(BaseModel):
    """Emitter creation payload."""

    external_id: str | None = Field(default=None, max_length=128)
    ruc: str = Field(min_length=8, max_length=16)
    dv: str = Field(min_length=1, max_length=4)
    legal_name: str = Field(min_length=1, max_length=255)
    tax_environment: Literal["test", "production"]
    csc: str | None = Field(default=None, max_length=255)
    csc_id: str | None = Field(default=None, max_length=16)


class EmitterUpdateRequest(BaseModel):
    """Emitter update payload."""

    legal_name: str | None = Field(default=None, min_length=1, max_length=255)
    tax_environment: Literal["test", "production"] | None = None
    csc: str | None = Field(default=None, max_length=255)
    csc_id: str | None = Field(default=None, max_length=16)


class EmitterResponse(BaseModel):
    """Emitter response payload."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    external_id: str | None
    ruc: str
    dv: str
    legal_name: str
    tax_environment: str
    status: str
    csc: str | None
    csc_id: str | None
    created_at: datetime
    updated_at: datetime
