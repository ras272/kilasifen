"""Job domain models."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class Job:
    """A persisted async job."""

    id: str
    emitter_id: str | None
    related_entity_type: str | None
    related_entity_id: str | None
    job_type: str
    status: str
    attempts: int
    error_snapshot: dict | None
    scheduled_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    worker_correlation_id: str | None
    created_at: datetime
    updated_at: datetime
