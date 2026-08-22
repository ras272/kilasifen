"""RQ queue adapter for background jobs."""

from typing import Protocol, cast

from rq import Queue, Retry
from rq.exceptions import NoSuchJobError
from rq.job import Job as RqJob

from kilasifen.domain.jobs.models import Job
from kilasifen.logging import get_correlation_id


class WebhookJobQueue(Protocol):
    """Queue contract for webhook delivery jobs."""

    def enqueue_webhook_delivery(
        self,
        job: Job,
        *,
        database_url: str,
        encryption_key: str,
    ):
        """Enqueue a webhook delivery job."""


class RqJobQueue:
    """Thin adapter around an RQ queue."""

    def __init__(self, queue: Queue):
        self.queue = queue

    def enqueue_document_emit(
        self,
        job: Job,
        *,
        database_url: str,
        encryption_key: str,
    ) -> RqJob:
        """Enqueue only a durable identifier; workers load secrets from their env."""

        del database_url, encryption_key

        return self.enqueue_outbox_job(
            job_id=job.id,
            job_type=job.job_type,
            correlation_id=get_correlation_id(),
        )

    def enqueue_webhook_delivery(
        self,
        job: Job,
        *,
        database_url: str,
        encryption_key: str,
    ) -> RqJob:
        """Enqueue only a durable identifier; workers load secrets from their env."""

        del database_url, encryption_key

        return self.enqueue_outbox_job(
            job_id=job.id,
            job_type=job.job_type,
            correlation_id=get_correlation_id(),
        )

    def enqueue_event_submit(
        self,
        job: Job,
        *,
        database_url: str,
        encryption_key: str,
    ) -> RqJob:
        """Enqueue an event identifier with bounded automatic retries."""

        del database_url, encryption_key
        return self.enqueue_outbox_job(
            job_id=job.id,
            job_type=job.job_type,
            correlation_id=get_correlation_id(),
        )

    def enqueue_outbox_job(
        self,
        *,
        job_id: str,
        job_type: str,
        correlation_id: str | None,
    ) -> RqJob:
        """Publish once by durable job id, replacing only a terminal RQ record."""

        existing = self._fetch_job(job_id)
        if existing is not None:
            raw_status = existing.get_status(refresh=True)
            status = getattr(raw_status, "value", raw_status)
            if status in {"queued", "started", "deferred", "scheduled"}:
                return existing
            existing.delete()

        try:
            func, retry = _job_runtime()[job_type]
        except KeyError as exc:
            raise ValueError(f"Unsupported outbox job type: {job_type}") from exc
        return cast(
            RqJob,
            self.queue.enqueue_call(
                func=func,
                kwargs={"job_id": job_id},
                job_id=job_id,
                meta={"correlation_id": correlation_id},
                retry=retry,
            ),
        )

    def _fetch_job(self, job_id: str) -> RqJob | None:
        try:
            return RqJob.fetch(job_id, connection=self.queue.connection)
        except NoSuchJobError:
            return None


def _job_runtime():
    from kilasifen.infrastructure.jobs.workers import (
        process_document_job,
        process_event_job,
        process_webhook_delivery_job,
    )

    return {
        "document.emit": (
            process_document_job,
            Retry(max=4, interval=[30, 120, 600, 1800]),
        ),
        "webhook.deliver": (
            process_webhook_delivery_job,
            Retry(max=7, interval=[10, 30, 120, 300, 900, 1800, 3600]),
        ),
        "event.submit": (
            process_event_job,
            Retry(max=4, interval=[30, 120, 600, 1800]),
        ),
    }
