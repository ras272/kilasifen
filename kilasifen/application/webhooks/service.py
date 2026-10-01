"""Application service layer for webhook workflows."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import uuid4

from kilasifen.application.emitters.guards import require_active_emitter
from kilasifen.application.jobs.service import JobService
from kilasifen.domain.common.errors import (
    ConflictError,
    NotFoundError,
    UnprocessableEntityError,
)
from kilasifen.domain.documents.models import Document
from kilasifen.domain.jobs.models import Job
from kilasifen.domain.webhooks.models import WebhookDelivery, WebhookEndpoint
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.webhooks.deliverer import (
    WebhookDeliverer,
    serialize_webhook_body,
)
from kilasifen.infrastructure.webhooks.security import (
    UnsafeWebhookUrlError,
    WebhookUrlPolicy,
)
from kilasifen.repositories.emitters import EmitterRepository
from kilasifen.repositories.jobs import JobRepository
from kilasifen.repositories.webhooks import WebhookRepository

WEBHOOK_TEST_EVENT_TYPE = "webhook.test"


@dataclass(frozen=True, slots=True)
class _ReplayableEvent:
    data: dict
    occurred_at: str


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
        url_policy: WebhookUrlPolicy | None = None,
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
        self.url_policy = url_policy or deliverer.url_policy

    def register_endpoint(
        self,
        *,
        emitter_id: str,
        url: str,
        secret: str,
        event_subscriptions: list[str] | None,
        retry_policy: dict | None,
    ) -> WebhookEndpoint:
        require_active_emitter(self.emitter_repository, emitter_id)
        if len(secret) < 32:
            raise UnprocessableEntityError("webhooks.secret_too_short")
        try:
            self.url_policy.resolve(url)
        except UnsafeWebhookUrlError as exc:
            raise UnprocessableEntityError(str(exc)) from exc

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

    def list_endpoints(self, emitter_id: str) -> list[WebhookEndpoint]:
        if self.emitter_repository.get(emitter_id) is None:
            raise NotFoundError("emitters.not_found")
        return self.webhook_repository.list_endpoints_for_emitter(emitter_id)

    def update_endpoint(
        self,
        *,
        emitter_id: str,
        endpoint_id: str,
        changes: dict[str, object],
    ) -> WebhookEndpoint:
        require_active_emitter(self.emitter_repository, emitter_id)
        endpoint = self.webhook_repository.get_endpoint(endpoint_id)
        if endpoint is None or endpoint.emitter_id != emitter_id:
            raise NotFoundError("webhooks.endpoint_not_found")

        persistence_changes: dict[str, object] = {}
        if "url" in changes:
            url = str(changes["url"])
            try:
                self.url_policy.resolve(url)
            except UnsafeWebhookUrlError as exc:
                raise UnprocessableEntityError(str(exc)) from exc
            persistence_changes["url"] = url
        if "secret" in changes:
            secret = str(changes["secret"])
            if len(secret) < 32:
                raise UnprocessableEntityError("webhooks.secret_too_short")
            persistence_changes["secret_encrypted"] = self.secret_store.encrypt_text(
                secret
            )
        for field in ("event_subscriptions", "retry_policy", "is_active"):
            if field in changes:
                persistence_changes[field] = changes[field]
        persistence_changes["updated_at"] = _now()

        updated = self.webhook_repository.update_endpoint_for_emitter(
            endpoint_id=endpoint_id,
            emitter_id=emitter_id,
            changes=persistence_changes,
        )
        if updated is None:
            raise NotFoundError("webhooks.endpoint_not_found")
        return updated

    def replay_delivery_for_emitter(
        self,
        *,
        emitter_id: str,
        endpoint_id: str,
        delivery_id: str,
    ) -> tuple[WebhookDelivery, Job]:
        """Re-deliver one existing event of this emitter to an endpoint.

        Only events the platform already generated can be replayed: the new
        delivery copies ``type``, ``data`` and ``occurred_at`` from the stored
        source delivery and gets a fresh delivery ID. Callers cannot supply an
        event type or payload, so a replay can never forge a fiscal event.
        """

        endpoint = self._active_endpoint_for_emitter(
            emitter_id=emitter_id,
            endpoint_id=endpoint_id,
        )
        source, _source_job = self.get_delivery_for_emitter(
            emitter_id=emitter_id,
            delivery_id=delivery_id,
        )
        event = _replayable_event(source)

        saved_delivery, job = self._create_delivery_job(
            endpoint=endpoint,
            event_type=source.event_type,
            payload=event.data,
            occurred_at=event.occurred_at,
        )
        self._enqueue_if_configured(job)
        return saved_delivery, job

    def send_test_event_for_emitter(
        self,
        *,
        emitter_id: str,
        endpoint_id: str,
    ) -> tuple[WebhookDelivery, Job]:
        """Deliver a synthetic ``webhook.test`` event to verify an endpoint.

        The payload is fixed by the platform and the event type lives outside
        the fiscal ``document.*``/``event.*`` namespaces, so it cannot be
        mistaken for a document or event status change.
        """

        endpoint = self._active_endpoint_for_emitter(
            emitter_id=emitter_id,
            endpoint_id=endpoint_id,
        )
        saved_delivery, job = self._create_delivery_job(
            endpoint=endpoint,
            event_type=WEBHOOK_TEST_EVENT_TYPE,
            payload={"test": True, "endpoint_id": endpoint.id},
        )
        self._enqueue_if_configured(job)
        return saved_delivery, job

    def publish_document_status(
        self, *, document: Document
    ) -> list[tuple[WebhookDelivery, Job]]:
        """Publish one normalized document-status event to subscribed endpoints."""

        event_type = _document_event_type(document.internal_status)
        payload = {
            "document_id": document.id,
            "external_id": document.external_id,
            "document_type": document.document_type,
            "internal_status": document.internal_status,
            "sifen_status": document.sifen_status,
            "sifen_result_code": document.sifen_result_code,
            "sifen_result_message": document.sifen_result_message,
        }
        return self.publish_event(
            emitter_id=document.emitter_id,
            event_type=event_type,
            payload=payload,
        )

    def publish_event(
        self,
        *,
        emitter_id: str,
        event_type: str,
        payload: dict | None,
    ) -> list[tuple[WebhookDelivery, Job]]:
        """Fan out one event to active endpoints subscribed to the event type."""

        require_active_emitter(self.emitter_repository, emitter_id)

        results: list[tuple[WebhookDelivery, Job]] = []
        endpoints = self.webhook_repository.list_endpoints_for_emitter(emitter_id)
        for endpoint in endpoints:
            if not endpoint.is_active:
                continue
            if not _supports_event(endpoint=endpoint, event_type=event_type):
                continue
            saved_delivery, job = self._create_delivery_job(
                endpoint=endpoint,
                event_type=event_type,
                payload=payload,
            )
            self._enqueue_if_configured(job)
            results.append((saved_delivery, job))
        return results

    def get_delivery(self, delivery_id: str) -> tuple[WebhookDelivery, Job | None]:
        delivery = self.webhook_repository.get_delivery(delivery_id)
        if delivery is None:
            raise NotFoundError("webhooks.delivery_not_found")
        job = self.job_service.get_for_entity("webhook_delivery", delivery.id)
        return delivery, job

    def get_delivery_for_emitter(
        self,
        *,
        emitter_id: str,
        delivery_id: str,
    ) -> tuple[WebhookDelivery, Job | None]:
        delivery, job = self.get_delivery(delivery_id)
        endpoint = self.webhook_repository.get_endpoint(delivery.webhook_endpoint_id)
        if endpoint is None or endpoint.emitter_id != emitter_id:
            raise NotFoundError("webhooks.delivery_not_found")
        return delivery, job

    def list_deliveries(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        emitter_id: str | None = None,
        endpoint_id: str | None = None,
        statuses: list[str] | None = None,
    ) -> list[WebhookDelivery]:
        if emitter_id and self.emitter_repository.get(emitter_id) is None:
            raise NotFoundError("emitters.not_found")
        return self.webhook_repository.list_recent_deliveries(
            limit=limit,
            offset=offset,
            endpoint_id=endpoint_id,
            emitter_id=emitter_id,
            statuses=statuses,
        )

    def process_delivery_attempt(self, *, job_id: str) -> dict[str, str | bool]:
        job = self.job_service.get_job(job_id)
        if job.related_entity_type != "webhook_delivery" or not job.related_entity_id:
            raise NotFoundError("jobs.webhook_delivery_context_not_found")

        delivery = self.webhook_repository.get_delivery(job.related_entity_id)
        if delivery is None:
            raise NotFoundError("webhooks.delivery_not_found")

        endpoint = self.webhook_repository.get_endpoint(delivery.webhook_endpoint_id)
        if endpoint is None:
            raise NotFoundError("webhooks.endpoint_not_found")

        if endpoint.emitter_id is None:
            raise ConflictError("webhooks.emitter_required")
        require_active_emitter(self.emitter_repository, endpoint.emitter_id)

        secret = self.secret_store.decrypt_text(endpoint.secret_encrypted)
        outcome = self.deliverer.deliver(
            url=endpoint.url,
            secret=secret,
            event_type=delivery.event_type,
            delivery_id=delivery.id,
            payload_snapshot=delivery.payload_snapshot,
            request_body=delivery.request_body,
        )

        current_attempt = job.attempts + 1
        max_attempts = _max_attempts(endpoint.retry_policy)
        retry_scheduled = outcome.retryable and current_attempt < max_attempts
        delivery_status = outcome.final_status
        if outcome.retryable and not retry_scheduled:
            delivery_status = "failed"

        updated_delivery = replace(
            delivery,
            request_body=delivery.request_body
            or serialize_webhook_body(delivery.payload_snapshot),
            attempt_number=current_attempt,
            request_at=outcome.request_at,
            response_code=outcome.response_code,
            response_body_snapshot=outcome.response_body_snapshot,
            final_status=delivery_status,
            updated_at=_now(),
        )
        self.webhook_repository.save_delivery(updated_delivery)

        if outcome.final_status == "delivered":
            updated_job = replace(
                job,
                status="succeeded",
                attempts=current_attempt,
                error_snapshot=None,
                finished_at=_now(),
                updated_at=_now(),
            )
        elif retry_scheduled:
            retry_at = _now() + timedelta(seconds=_retry_delay(current_attempt))
            updated_job = replace(
                job,
                status="retry_scheduled",
                attempts=current_attempt,
                error_snapshot={"category": "transport", "message": "retry_pending"},
                scheduled_at=retry_at,
                finished_at=None,
                updated_at=_now(),
            )
        else:
            updated_job = replace(
                job,
                status="failed",
                attempts=current_attempt,
                error_snapshot={
                    "category": "delivery_failed",
                    "message": (
                        "max_attempts_exhausted"
                        if outcome.retryable
                        else "non_retryable"
                    ),
                },
                finished_at=_now(),
                updated_at=_now(),
            )
        self.job_repository.save(updated_job)

        return {
            "job_id": updated_job.id,
            "job_status": updated_job.status,
            "delivery_id": updated_delivery.id,
            "delivery_status": updated_delivery.final_status,
            "retryable": retry_scheduled,
        }

    def _active_endpoint_for_emitter(
        self,
        *,
        emitter_id: str,
        endpoint_id: str,
    ) -> WebhookEndpoint:
        endpoint = self.webhook_repository.get_endpoint(endpoint_id)
        if endpoint is None or endpoint.emitter_id != emitter_id:
            raise NotFoundError("webhooks.endpoint_not_found")
        if not endpoint.is_active:
            raise ConflictError("webhooks.endpoint_inactive")
        require_active_emitter(self.emitter_repository, emitter_id)
        return endpoint

    def _create_delivery_job(
        self,
        *,
        endpoint: WebhookEndpoint,
        event_type: str,
        payload: dict | None,
        occurred_at: str | None = None,
    ) -> tuple[WebhookDelivery, Job]:
        timestamp = _now()
        delivery_id = str(uuid4())
        envelope = {
            "type": event_type,
            "delivery_id": delivery_id,
            "occurred_at": occurred_at or timestamp.isoformat(),
            "data": payload or {},
        }
        request_body = serialize_webhook_body(envelope)
        delivery = WebhookDelivery(
            id=delivery_id,
            webhook_endpoint_id=endpoint.id,
            event_type=event_type,
            payload_snapshot=envelope,
            request_body=request_body,
            attempt_number=0,
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
        return saved_delivery, job

    def _enqueue_if_configured(self, job: Job) -> None:
        if self.database_url and self.encryption_key:
            self.queue.enqueue_webhook_delivery(
                job,
                database_url=self.database_url,
                encryption_key=self.encryption_key,
            )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _replayable_event(delivery: WebhookDelivery) -> _ReplayableEvent:
    """Return the stored event of a delivery, or refuse when it is incomplete."""

    snapshot = delivery.payload_snapshot
    if not isinstance(snapshot, dict):
        raise ConflictError("webhooks.delivery_not_replayable")
    data = snapshot.get("data")
    occurred_at = snapshot.get("occurred_at")
    if (
        snapshot.get("type") != delivery.event_type
        or not isinstance(data, dict)
        or not isinstance(occurred_at, str)
    ):
        raise ConflictError("webhooks.delivery_not_replayable")
    return _ReplayableEvent(data=data, occurred_at=occurred_at)


def _supports_event(*, endpoint: WebhookEndpoint, event_type: str) -> bool:
    subscriptions = [
        item.strip()
        for item in (endpoint.event_subscriptions or [])
        if item and item.strip()
    ]
    if not subscriptions:
        return True
    if "*" in subscriptions or event_type in subscriptions:
        return True
    for subscription in subscriptions:
        if subscription.endswith(".*"):
            prefix = subscription[: -len("*")]
            if event_type.startswith(prefix):
                return True
    return False


def _document_event_type(internal_status: str | None) -> str:
    normalized = (internal_status or "").strip().lower()
    if normalized in {
        "approved",
        "submitted",
        "rejected",
        "failed",
        "retry_pending",
        "reconciliation_required",
        "queued",
    }:
        return f"document.{normalized}"
    return "document.updated"


_WEBHOOK_RETRY_DELAYS = (10, 30, 120, 300, 900, 1800, 3600)


def _max_attempts(retry_policy: dict | None) -> int:
    raw_value = (retry_policy or {}).get("max_attempts", 5)
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        return 5
    return min(max(raw_value, 1), 8)


def _retry_delay(attempt_number: int) -> int:
    index = min(max(attempt_number - 1, 0), len(_WEBHOOK_RETRY_DELAYS) - 1)
    return _WEBHOOK_RETRY_DELAYS[index]
