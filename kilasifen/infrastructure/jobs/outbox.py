"""Transactional job staging and recoverable DB-to-RQ dispatch."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from kilasifen.domain.jobs.models import Job
from kilasifen.domain.jobs.outbox import JobOutboxMessage
from kilasifen.infrastructure.db.repositories.job_outbox import (
    SqlAlchemyJobOutboxRepository,
)
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.logging import get_correlation_id

logger = logging.getLogger(__name__)

_QUEUE_BY_JOB_TYPE = {
    "document.emit": "documents",
    "event.submit": "events",
    "webhook.deliver": "webhooks",
}


class SqlAlchemyJobOutboxQueue:
    """Queue-port adapter that stages dispatch in the current DB transaction."""

    def __init__(self, repository: SqlAlchemyJobOutboxRepository):
        self.repository = repository

    def enqueue_document_emit(self, job: Job, **runtime: str) -> JobOutboxMessage:
        del runtime
        return self._stage(job, expected_type="document.emit")

    def enqueue_event_submit(self, job: Job, **runtime: str) -> JobOutboxMessage:
        del runtime
        return self._stage(job, expected_type="event.submit")

    def enqueue_webhook_delivery(self, job: Job, **runtime: str) -> JobOutboxMessage:
        del runtime
        return self._stage(job, expected_type="webhook.deliver")

    def _stage(self, job: Job, *, expected_type: str) -> JobOutboxMessage:
        if job.job_type != expected_type:
            raise ValueError(
                f"Cannot stage {job.job_type!r} through {expected_type!r} queue port"
            )
        return self.repository.stage(
            job_id=job.id,
            queue_name=_QUEUE_BY_JOB_TYPE[job.job_type],
            correlation_id=get_correlation_id(),
        )


class OutboxRuntimeQueue(Protocol):
    """Minimal runtime publisher used by the dispatcher."""

    def enqueue_outbox_job(
        self,
        *,
        job_id: str,
        job_type: str,
        correlation_id: str | None,
    ) -> object:
        """Publish or resolve an existing RQ job by durable id."""


class JobOutboxDispatcher:
    """Lease committed outbox rows and publish them idempotently to RQ."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        queues: Mapping[str, OutboxRuntimeQueue],
        worker_id: str | None = None,
        lease_seconds: int = 30,
        retry_delays: tuple[int, ...] = (5, 30, 120, 600, 1800),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.queues = queues
        self.worker_id = worker_id or str(uuid4())
        self.lease_seconds = lease_seconds
        self.retry_delays = retry_delays
        self.clock = clock or _now

    def dispatch_once(self, *, limit: int = 100) -> int:
        """Publish at most ``limit`` committed messages; return confirmed count."""

        messages = self._claim(limit=limit)
        published = 0
        for message in messages:
            if self._dispatch(message):
                published += 1
        return published

    def _claim(self, *, limit: int) -> list[JobOutboxMessage]:
        now = self.clock()
        with self.session_factory() as session, session.begin():
            repository = SqlAlchemyJobOutboxRepository(session)
            return repository.claim_batch(
                worker_id=self.worker_id,
                now=now,
                locked_until=now + timedelta(seconds=self.lease_seconds),
                limit=limit,
            )

    def _dispatch(self, message: JobOutboxMessage) -> bool:
        try:
            job = self._load_job(message.job_id)
            if job is None:
                raise RuntimeError("persisted job is missing")
            if job.status == "queued":
                queue = self.queues.get(message.queue_name)
                if queue is None:
                    raise RuntimeError("runtime queue is not configured")
                queue.enqueue_outbox_job(
                    job_id=job.id,
                    job_type=job.job_type,
                    correlation_id=message.correlation_id,
                )
            self._mark_published(message.id)
            return True
        except Exception as exc:
            logger.error(
                "jobs.outbox.publish_failed",
                extra={
                    "outbox_id": message.id,
                    "job_id": message.job_id,
                    "error_type": type(exc).__name__,
                },
            )
            self._mark_failed(message, exc)
            return False

    def _load_job(self, job_id: str) -> Job | None:
        with self.session_factory() as session:
            return SqlAlchemyJobRepository(session).get(job_id)

    def _mark_published(self, message_id: str) -> None:
        now = self.clock()
        with self.session_factory() as session, session.begin():
            updated = SqlAlchemyJobOutboxRepository(session).mark_published(
                message_id=message_id,
                worker_id=self.worker_id,
                published_at=now,
            )
            if not updated:
                raise RuntimeError("outbox lease was lost before confirmation")

    def _mark_failed(self, message: JobOutboxMessage, exc: Exception) -> None:
        now = self.clock()
        retry_index = min(max(message.attempts - 1, 0), len(self.retry_delays) - 1)
        delay = self.retry_delays[retry_index]
        safe_error = f"{type(exc).__name__}: queue publication failed"
        with self.session_factory() as session, session.begin():
            SqlAlchemyJobOutboxRepository(session).mark_failed(
                message_id=message.id,
                worker_id=self.worker_id,
                available_at=now + timedelta(seconds=delay),
                last_error=safe_error,
                updated_at=now,
            )


def _now() -> datetime:
    return datetime.now(UTC)
