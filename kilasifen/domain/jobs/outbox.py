"""Domain state for durable job dispatch."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class JobOutboxMessage:
    """A durable request to publish one persisted job to its runtime queue."""

    id: str
    job_id: str
    queue_name: str
    correlation_id: str | None
    status: str
    attempts: int
    available_at: datetime
    locked_until: datetime | None
    locked_by: str | None
    published_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime
