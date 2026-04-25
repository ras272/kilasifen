"""Pydantic schemas for stamping APIs."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class StampingCreateRequest(BaseModel):
    """Stamping creation payload."""

    number: str = Field(min_length=1, max_length=32)
    start_date: date
    end_date: date | None = None


class StampingResponse(BaseModel):
    """Stamping response payload."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    emitter_id: str
    number: str
    start_date: date
    end_date: date | None
    is_active: bool
    status: str
    created_at: datetime
    updated_at: datetime
