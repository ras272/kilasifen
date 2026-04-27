"""RQ queue adapter for background jobs."""

from typing import Protocol

from rq import Queue
from rq.job import Job as RqJob

from kilasifen.domain.jobs.models import Job
from kilasifen.infrastructure.jobs.workers import (
    process_document_job,
    process_webhook_delivery_job,
)
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
        """Enqueue document emission work."""

        return self.queue.enqueue_call(
            func=process_document_job,
            kwargs={
                "job_id": job.id,
                "database_url": database_url,
                "encryption_key": encryption_key,
            },
            job_id=job.id,
            meta={"correlation_id": get_correlation_id()},
        )

    def enqueue_webhook_delivery(
        self,
        job: Job,
        *,
        database_url: str,
        encryption_key: str,
    ) -> RqJob:
        """Enqueue webhook delivery work."""

        return self.queue.enqueue_call(
            func=process_webhook_delivery_job,
            kwargs={
                "job_id": job.id,
                "database_url": database_url,
                "encryption_key": encryption_key,
            },
            job_id=job.id,
            meta={"correlation_id": get_correlation_id()},
        )
