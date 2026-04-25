import hashlib
import hmac
import json
from datetime import UTC, datetime

from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.jobs.models import Job
from kilasifen.domain.webhooks.models import WebhookDelivery, WebhookEndpoint
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.repositories.emitters import SqlAlchemyEmitterRepository
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.repositories.webhooks import SqlAlchemyWebhookRepository
from kilasifen.infrastructure.db.session import build_engine, build_session_factory, session_scope
from kilasifen.infrastructure.jobs.workers import process_webhook_delivery_job
from kilasifen.infrastructure.webhooks.deliverer import WebhookDeliverer


def test_process_webhook_delivery_job_signs_payload_and_marks_delivered(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'webhook-success.db'}"
    encryption_key = _fernet_key()
    _seed_webhook_job_context(database_url=database_url, encryption_key=encryption_key)

    captured = {}

    def sender(*, url: str, body: str, headers: dict[str, str], timeout: float):
        del timeout
        captured["url"] = url
        captured["body"] = body
        captured["headers"] = headers
        return 200, "ok"

    payload = process_webhook_delivery_job(
        job_id="job-1",
        database_url=database_url,
        encryption_key=encryption_key,
        deliverer=WebhookDeliverer(sender=sender),
    )

    assert payload["job_status"] == "succeeded"
    assert payload["delivery_status"] == "delivered"

    expected_signature = hmac.new(
        b"top-secret",
        captured["body"].encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert captured["headers"]["X-Kila-Signature"] == f"sha256={expected_signature}"


def test_process_webhook_delivery_job_marks_retry_pending_on_retryable_failure(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'webhook-fail.db'}"
    encryption_key = _fernet_key()
    _seed_webhook_job_context(database_url=database_url, encryption_key=encryption_key)

    def sender(*, url: str, body: str, headers: dict[str, str], timeout: float):
        del url, body, headers, timeout
        return 503, "temporarily unavailable"

    payload = process_webhook_delivery_job(
        job_id="job-1",
        database_url=database_url,
        encryption_key=encryption_key,
        deliverer=WebhookDeliverer(sender=sender),
    )

    assert payload["job_status"] == "retry_scheduled"
    assert payload["delivery_status"] == "retry_pending"


def _seed_webhook_job_context(*, database_url: str, encryption_key: str) -> None:
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    store = EncryptedCertificateStore(encryption_key)

    emitter = Emitter(
        id="emitter-1",
        external_id="erp-ares",
        ruc="80024135",
        dv="5",
        legal_name="ARES PARAGUAY SRL",
        tax_environment="test",
        status="active",
        csc="ABCD0000000000000000000000000000",
        csc_id="0001",
        created_at=_now(),
        updated_at=_now(),
    )
    endpoint = WebhookEndpoint(
        id="endpoint-1",
        emitter_id="emitter-1",
        url="https://erp.example.com/hooks/kila",
        secret_encrypted=store.encrypt_text("top-secret"),
        event_subscriptions=["document.approved"],
        is_active=True,
        retry_policy={"max_attempts": 3},
        created_at=_now(),
        updated_at=_now(),
    )
    delivery = WebhookDelivery(
        id="delivery-1",
        webhook_endpoint_id="endpoint-1",
        event_type="document.approved",
        payload_snapshot={
            "type": "document.approved",
            "delivery_id": "delivery-1",
            "data": {"document_id": "doc-1", "status": "approved"},
        },
        attempt_number=1,
        request_at=None,
        response_code=None,
        response_body_snapshot=None,
        final_status="pending",
        created_at=_now(),
        updated_at=_now(),
    )
    job = Job(
        id="job-1",
        emitter_id="emitter-1",
        related_entity_type="webhook_delivery",
        related_entity_id="delivery-1",
        job_type="webhook.deliver",
        status="queued",
        attempts=0,
        error_snapshot=None,
        scheduled_at=_now(),
        started_at=None,
        finished_at=None,
        worker_correlation_id=None,
        created_at=_now(),
        updated_at=_now(),
    )

    with session_scope(session_factory) as session:
        SqlAlchemyEmitterRepository(session).save(emitter)
        webhook_repository = SqlAlchemyWebhookRepository(session)
        webhook_repository.save_endpoint(endpoint)
        webhook_repository.save_delivery(delivery)
        SqlAlchemyJobRepository(session).save(job)


def _now() -> datetime:
    return datetime.now(UTC)


def _fernet_key() -> str:
    return "4fV1_r04jQs6C1UNq9qS4RuCs1oQcWzER8GqW04A1lE="
