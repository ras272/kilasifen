"""Application service layer for operational admin console workflows."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from kilasifen.application.certificates.service import CertificateService
from kilasifen.application.emitters.service import EmitterService
from kilasifen.application.jobs.service import JobService
from kilasifen.domain.certificates.models import Certificate
from kilasifen.domain.common.errors import ConflictError
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.jobs.models import Job
from kilasifen.domain.stampings.models import Stamping
from kilasifen.domain.webhooks.models import WebhookDelivery, WebhookEndpoint
from kilasifen.repositories.certificates import CertificateRepository
from kilasifen.repositories.documents import DocumentRepository
from kilasifen.repositories.emitters import EmitterRepository
from kilasifen.repositories.jobs import JobRepository
from kilasifen.repositories.stampings import StampingRepository
from kilasifen.repositories.webhooks import WebhookRepository


class DocumentEmissionQueue(Protocol):
    """Queue contract for document emission jobs."""

    def enqueue_document_emit(self, job: Job, *, database_url: str, encryption_key: str):
        """Enqueue one document emission job."""


class WebhookDeliveryQueue(Protocol):
    """Queue contract for webhook delivery jobs."""

    def enqueue_webhook_delivery(
        self,
        job: Job,
        *,
        database_url: str,
        encryption_key: str,
    ):
        """Enqueue one webhook delivery job."""


@dataclass(slots=True)
class AdminWebhookDeliveryRow:
    """Webhook delivery plus endpoint/emitter context for templates."""

    delivery: WebhookDelivery
    endpoint: WebhookEndpoint
    emitter: Emitter | None
    job: Job | None


@dataclass(slots=True)
class AdminEmitterDetail:
    """All read models needed by the emitter detail screen."""

    emitter: Emitter
    certificates: list[Certificate]
    stampings: list[Stamping]
    documents: list[Document]
    jobs: list[Job]
    webhook_endpoints: list[WebhookEndpoint]
    failed_webhook_deliveries: list[AdminWebhookDeliveryRow]


class AdminConsoleService:
    """Read-heavy operations and low-risk actions for console operators."""

    def __init__(
        self,
        *,
        emitter_repository: EmitterRepository,
        certificate_repository: CertificateRepository,
        stamping_repository: StampingRepository,
        document_repository: DocumentRepository,
        job_repository: JobRepository,
        webhook_repository: WebhookRepository,
        certificate_service: CertificateService,
        document_queue: DocumentEmissionQueue | None,
        webhook_queue: WebhookDeliveryQueue | None,
        database_url: str | None,
        encryption_key: str | None,
    ):
        self.emitter_repository = emitter_repository
        self.certificate_repository = certificate_repository
        self.stamping_repository = stamping_repository
        self.document_repository = document_repository
        self.job_repository = job_repository
        self.webhook_repository = webhook_repository
        self.certificate_service = certificate_service
        self.emitter_service = EmitterService(emitter_repository)
        self.job_service = JobService(job_repository)
        self.document_queue = document_queue
        self.webhook_queue = webhook_queue
        self.database_url = database_url
        self.encryption_key = encryption_key

    def list_emitters(self) -> list[Emitter]:
        """List all emitters for the console home."""

        return self.emitter_repository.list_all()

    def get_emitter_detail(
        self,
        emitter_id: str,
        *,
        limit: int = 20,
    ) -> AdminEmitterDetail:
        """Gather one emitter operational snapshot."""

        emitter = self.emitter_service.get_emitter(emitter_id)
        endpoints = self.webhook_repository.list_endpoints_for_emitter(emitter_id)
        failed_rows: list[AdminWebhookDeliveryRow] = []
        for endpoint in endpoints:
            deliveries = self.webhook_repository.list_recent_deliveries(
                limit=limit,
                endpoint_id=endpoint.id,
                statuses=["failed", "retry_pending"],
            )
            failed_rows.extend(
                AdminWebhookDeliveryRow(
                    delivery=delivery,
                    endpoint=endpoint,
                    emitter=emitter,
                    job=self.job_repository.get_for_entity("webhook_delivery", delivery.id),
                )
                for delivery in deliveries
            )
        failed_rows.sort(key=lambda item: item.delivery.created_at, reverse=True)

        return AdminEmitterDetail(
            emitter=emitter,
            certificates=self.certificate_repository.list_for_emitter(emitter_id),
            stampings=self.stamping_repository.list_for_emitter(emitter_id),
            documents=self.document_repository.list_recent(limit=limit, emitter_id=emitter_id),
            jobs=self.job_repository.list_recent(limit=limit, emitter_id=emitter_id),
            webhook_endpoints=endpoints,
            failed_webhook_deliveries=failed_rows[:limit],
        )

    def list_documents(
        self,
        *,
        limit: int = 50,
        emitter_id: str | None = None,
    ) -> list[Document]:
        """List recent documents for global operations."""

        return self.document_repository.list_recent(limit=limit, emitter_id=emitter_id)

    def list_jobs(
        self,
        *,
        limit: int = 50,
        emitter_id: str | None = None,
        status: str | None = None,
    ) -> list[Job]:
        """List recent jobs for global operations."""

        return self.job_repository.list_recent(limit=limit, emitter_id=emitter_id, status=status)

    def list_failed_webhook_deliveries(
        self,
        *,
        limit: int = 50,
        emitter_id: str | None = None,
    ) -> list[AdminWebhookDeliveryRow]:
        """List recent webhook failures/retries for operator visibility."""

        deliveries = self.webhook_repository.list_recent_deliveries(
            limit=limit * 3,
            statuses=["failed", "retry_pending"],
        )
        rows: list[AdminWebhookDeliveryRow] = []
        endpoint_cache: dict[str, WebhookEndpoint] = {}
        emitter_cache: dict[str, Emitter | None] = {}
        for delivery in deliveries:
            endpoint = endpoint_cache.get(delivery.webhook_endpoint_id)
            if endpoint is None:
                endpoint = self.webhook_repository.get_endpoint(delivery.webhook_endpoint_id)
                if endpoint is None:
                    continue
                endpoint_cache[endpoint.id] = endpoint

            current_emitter_id = endpoint.emitter_id
            if emitter_id and current_emitter_id != emitter_id:
                continue

            emitter = None
            if current_emitter_id:
                if current_emitter_id in emitter_cache:
                    emitter = emitter_cache[current_emitter_id]
                else:
                    emitter = self.emitter_repository.get(current_emitter_id)
                    emitter_cache[current_emitter_id] = emitter

            rows.append(
                AdminWebhookDeliveryRow(
                    delivery=delivery,
                    endpoint=endpoint,
                    emitter=emitter,
                    job=self.job_repository.get_for_entity("webhook_delivery", delivery.id),
                )
            )
            if len(rows) >= limit:
                break
        return rows

    def activate_certificate(self, certificate_id: str) -> Certificate:
        """Activate one certificate for the emitter."""

        return self.certificate_service.activate_certificate(certificate_id)

    def retry_job(self, job_id: str) -> Job:
        """Re-queue supported failed jobs with a fresh queued status."""

        job = self.job_service.get_job(job_id)
        if job.job_type not in {"document.emit", "webhook.deliver"}:
            raise ConflictError("jobs.retry_unsupported")
        if job.status == "succeeded":
            raise ConflictError("jobs.retry_not_allowed")

        timestamp = _now()
        retry_job = replace(
            job,
            status="queued",
            scheduled_at=timestamp,
            started_at=None,
            finished_at=None,
            error_snapshot=None,
            updated_at=timestamp,
        )
        saved = self.job_repository.save(retry_job)
        self._enqueue_retry(saved)
        return saved

    def _enqueue_retry(self, job: Job) -> None:
        if not self.database_url or not self.encryption_key:
            raise ConflictError("jobs.retry_unavailable")

        if job.job_type == "document.emit":
            if self.document_queue is None:
                raise ConflictError("jobs.retry_unavailable")
            self.document_queue.enqueue_document_emit(
                job,
                database_url=self.database_url,
                encryption_key=self.encryption_key,
            )
            return

        if job.job_type == "webhook.deliver":
            if self.webhook_queue is None:
                raise ConflictError("jobs.retry_unavailable")
            self.webhook_queue.enqueue_webhook_delivery(
                job,
                database_url=self.database_url,
                encryption_key=self.encryption_key,
            )
            return

        raise ConflictError("jobs.retry_unsupported")


def _now() -> datetime:
    return datetime.now(UTC)

