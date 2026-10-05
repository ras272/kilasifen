"""Pydantic schemas for job APIs."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from kilasifen.api.schemas.common import Pagination, SuccessEnvelope


class JobResponse(BaseModel):
    """Job asíncrono (emisión, evento o entrega de webhook)."""

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


class JobData(BaseModel):
    """Job consultado."""

    job: JobResponse


class JobListData(BaseModel):
    """Página de jobs."""

    jobs: list[JobResponse]
    pagination: Pagination


class JobEnvelope(SuccessEnvelope[JobData]):
    """Respuesta con un job."""


class JobListEnvelope(SuccessEnvelope[JobListData]):
    """Respuesta con una página de jobs."""
