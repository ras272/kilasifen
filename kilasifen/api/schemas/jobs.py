"""Pydantic schemas for job APIs."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class JobResponse(BaseModel):
    """Job response payload."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    emitter_id: str | None
    related_entity_type: str | None
    related_entity_id: str | None
    job_type: str
    status: str
    attempts: int
    error_snapshot: dict[str, Any] | None
    scheduled_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    worker_correlation_id: str | None
    created_at: datetime
    updated_at: datetime
