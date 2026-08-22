"""Durable job-outbox repository interface."""

from abc import ABC, abstractmethod
from datetime import datetime

from kilasifen.domain.jobs.outbox import JobOutboxMessage


class JobOutboxRepository(ABC):
    """Persistence contract for transactional job dispatch."""

    @abstractmethod
    def stage(
        self,
        *,
        job_id: str,
        queue_name: str,
        correlation_id: str | None,
    ) -> JobOutboxMessage:
        """Stage one job in the caller's database transaction."""

    @abstractmethod
    def claim_batch(
        self,
        *,
        worker_id: str,
        now: datetime,
        locked_until: datetime,
        limit: int,
    ) -> list[JobOutboxMessage]:
        """Atomically lease dispatchable messages to one dispatcher replica."""

    @abstractmethod
    def mark_published(
        self,
        *,
        message_id: str,
        worker_id: str,
        published_at: datetime,
    ) -> bool:
        """Confirm a leased message was published or already completed."""

    @abstractmethod
    def mark_failed(
        self,
        *,
        message_id: str,
        worker_id: str,
        available_at: datetime,
        last_error: str,
        updated_at: datetime,
    ) -> bool:
        """Release a failed message for a later bounded retry."""

    @abstractmethod
    def get(self, message_id: str) -> JobOutboxMessage | None:
        """Load one message for diagnostics and tests."""

    @abstractmethod
    def get_for_job(self, job_id: str) -> JobOutboxMessage | None:
        """Load the unique dispatch record for a job."""
