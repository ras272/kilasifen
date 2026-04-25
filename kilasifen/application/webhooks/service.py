"""Application service layer for webhook workflows."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from kilasifen.application.jobs.service import JobService
from kilasifen.domain.common.errors import ConflictError, NotFoundError
from kilasifen.domain.jobs.models import Job
from kilasifen.domain.webhooks.models import WebhookDelivery, WebhookEndpoint
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.webhooks.deliverer import WebhookDeliverer
from kilasifen.repositories.emitters import EmitterRepository
from kilasifen.repositories.jobs import JobRepository
from kilasifen.repositories.webhooks import WebhookRepository


class WebhookJobQueue(Protocol):
    """Queue contract for webhook delivery jobs."""

    def enqueue_webhook_delivery(
        self,
        job: Job,
        *,
        database_url: str,
        encryption_key: str,
    ):
        """Enqueue one webhook delivery job."""


class WebhookService:
    """Use cases for webhook endpoint and delivery management."""

    def __init__(
        self,
        *,
        webhook_repository: WebhookRepository,
        emitter_repository: EmitterRepository,
        job_repository: JobRepository,
        secret_store: EncryptedCertificateStore,
        queue: WebhookJobQueue,
        deliverer: WebhookDeliverer,
        database_url: str | None = None,
        encryption_key: str | None = None,
    ):
        self.webhook_repository = webhook_repository
        self.emitter_repository = emitter_repository
        self.job_repository = job_repository
        self.job_service = JobService(job_repository)
        self.secret_store = secret_store
        self.queue = queue
        self.deliverer = deliverer
        self.database_url = database_url
        self.encryption_key = encryption_key

    def register_endpoint(
        self,
        *,
        emitter_id: str,
        url: str,
        secret: str,
        event_subscriptions: list[str] | None,
        retry_policy: dict | None,
    ) -> WebhookEndpoint:
        if self.emitter_repository.get(emitter_id) is None:
            raise NotFoundError("emitters.not_found")

        timestamp = _now()
        endpoint = WebhookEndpoint(
            id=str(uuid4()),
            emitter_id=emitter_id,
            url=url,
            secret_encrypted=self.secret_store.encrypt_text(secret),
            event_subscriptions=event_subscriptions,
            is_active=True,
            retry_policy=retry_policy,
            created_at=timestamp,
            updated_at=timestamp,
        )
        return self.webhook_repository.save_endpoint(endpoint)

    def get_secret_preview(self, endpoint: WebhookEndpoint) -> str:
        secret = self.secret_store.decrypt_text(endpoint.secret_encrypted)
        return _secret_preview(secret)

    def list_endpoints(self, emitter_id: str) -> list[WebhookEndpoint]:
        if self.emitter_repository.get(emitter_id) is None:
            raise NotFoundError("emitters.not_found")
        return self.webhook_repository.list_endpoints_for_emitter(emitter_id)

    def replay_delivery(
        self,
        *,
        endpoint_id: str,
        event_type: str,
        payload: dict | None,
    ) -> tuple[WebhookDelivery, Job]:
        endpoint = self.webhook_repository.get_endpoint(endpoint_id)
        if endpoint is None:
            raise NotFoundError("webhooks.endpoint_not_found")
        if not endpoint.is_active:
            raise ConflictError("webhooks.endpoint_inactive")

        timestamp = _now()
        delivery_id = str(uuid4())
        envelope = {
            "type": event_type,
            "delivery_id": delivery_id,
            "occurred_at": timestamp.isoformat(),
            "data": payload or {},
        }
        delivery = WebhookDelivery(
            id=delivery_id,
            webhook_endpoint_id=endpoint.id,
            event_type=event_type,
            payload_snapshot=envelope,
            attempt_number=1,
            request_at=None,
            response_code=None,
            response_body_snapshot=None,
            final_status="pending",
            created_at=timestamp,
            updated_at=timestamp,
        )
        saved_delivery = self.webhook_repository.save_delivery(delivery)
        job = self.job_service.create_job(
            emitter_id=endpoint.emitter_id,
            related_entity_type="webhook_delivery",
            related_entity_id=saved_delivery.id,
            job_type="webhook.deliver",
        )

        if self.database_url and self.encryption_key:
            self.queue.enqueue_webhook_delivery(
                job,
                database_url=self.database_url,
                encryption_key=self.encryption_key,
            )

        return saved_delivery, job

    def get_delivery(self, delivery_id: str) -> tuple[WebhookDelivery, Job | None]:
        delivery = self.webhook_repository.get_delivery(delivery_id)
        if delivery is None:
            raise NotFoundError("webhooks.delivery_not_found")
        job = self.job_service.get_for_entity("webhook_delivery", delivery.id)
        return delivery, job

    def process_delivery_attempt(self, *, job_id: str) -> dict[str, str]:
        job = self.job_service.get_job(job_id)
        if job.related_entity_type != "webhook_delivery" or not job.related_entity_id:
            raise NotFoundError("jobs.webhook_delivery_context_not_found")

        delivery = self.webhook_repository.get_delivery(job.related_entity_id)
        if delivery is None:
            raise NotFoundError("webhooks.delivery_not_found")

        endpoint = self.webhook_repository.get_endpoint(delivery.webhook_endpoint_id)
        if endpoint is None:
            raise NotFoundError("webhooks.endpoint_not_found")

        secret = self.secret_store.decrypt_text(endpoint.secret_encrypted)
        outcome = self.deliverer.deliver(
            url=endpoint.url,
            secret=secret,
            event_type=delivery.event_type,
            delivery_id=delivery.id,
            payload_snapshot=delivery.payload_snapshot,
        )

        updated_delivery = replace(
            delivery,
            request_at=outcome.request_at,
            response_code=outcome.response_code,
            response_body_snapshot=outcome.response_body_snapshot,
            final_status=outcome.final_status,
            updated_at=_now(),
        )
        self.webhook_repository.save_delivery(updated_delivery)

        if outcome.final_status == "delivered":
            updated_job = replace(
                job,
                status="succeeded",
                attempts=job.attempts + 1,
                error_snapshot=None,
                updated_at=_now(),
            )
        elif outcome.retryable:
            updated_job = replace(
                job,
                status="retry_scheduled",
                attempts=job.attempts + 1,
                error_snapshot={"category": "transport", "message": "retry_pending"},
                updated_at=_now(),
            )
        else:
            updated_job = replace(
                job,
                status="failed",
                attempts=job.attempts + 1,
                error_snapshot={"category": "delivery_failed", "message": "non_retryable"},
                updated_at=_now(),
            )
        self.job_repository.save(updated_job)

        return {
            "job_id": updated_job.id,
            "job_status": updated_job.status,
            "delivery_id": updated_delivery.id,
            "delivery_status": updated_delivery.final_status,
        }


def _now() -> datetime:
    return datetime.now(UTC)


def _secret_preview(secret: str) -> str:
    if len(secret) <= 4:
        return "***"
    return f"{secret[:2]}***{secret[-2:]}"
