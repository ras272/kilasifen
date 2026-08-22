from datetime import UTC, datetime

import pytest

from kilasifen.application.webhooks.service import WebhookService
from kilasifen.domain.common.errors import ConflictError
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.jobs.models import Job
from kilasifen.domain.webhooks.models import WebhookDelivery, WebhookEndpoint
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.models import EmitterModel, WebhookEndpointModel
from kilasifen.infrastructure.db.repositories.emitters import (
    SqlAlchemyEmitterRepository,
)
from kilasifen.infrastructure.db.repositories.job_outbox import (
    SqlAlchemyJobOutboxRepository,
)
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.repositories.webhooks import (
    SqlAlchemyWebhookRepository,
)
from kilasifen.infrastructure.db.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from kilasifen.infrastructure.jobs.workers import process_webhook_delivery_job
from kilasifen.infrastructure.webhooks.deliverer import WebhookDeliverer
from kilasifen.infrastructure.webhooks.security import (
    WebhookUrlPolicy,
    verify_signature,
)
from kilasifen.testing.database import managed_test_database_url


def test_process_webhook_delivery_job_signs_payload_and_marks_delivered(
    tmp_path,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="webhook_delivery_success",
    ) as database_url:
        encryption_key = _fernet_key()
        _seed_webhook_job_context(
            database_url=database_url,
            encryption_key=encryption_key,
        )

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
            deliverer=WebhookDeliverer(sender=sender, url_policy=_public_policy()),
        )

        assert payload["job_status"] == "succeeded"
        assert payload["delivery_status"] == "delivered"

        verification = verify_signature(
            secret="top-secret",
            timestamp=captured["headers"]["X-Kila-Timestamp"],
            delivery_id=captured["headers"]["X-Kila-Delivery-ID"],
            event_type=captured["headers"]["X-Kila-Event"],
            body=captured["body"].encode("utf-8"),
            signature=captured["headers"]["X-Kila-Signature"],
        )
        assert verification.valid is True
        assert captured["headers"]["X-Kila-Signature-Version"] == "v1"


def test_queued_webhook_job_honors_inactive_emitter_before_secret_access(
    tmp_path,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="inactive_emitter_webhook_worker",
    ) as database_url:
        encryption_key = _fernet_key()
        _seed_webhook_job_context(
            database_url=database_url,
            encryption_key=encryption_key,
        )
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            emitter = session.get(EmitterModel, "emitter-1")
            endpoint = session.get(WebhookEndpointModel, "endpoint-1")
            assert emitter is not None and endpoint is not None
            emitter.status = "inactive"
            endpoint.secret_encrypted = "invalid-ciphertext-must-not-be-decrypted"

        def never_called_sender(**kwargs):
            del kwargs
            raise AssertionError("inactive emitter reached the webhook destination")

        with pytest.raises(ConflictError, match="emitters.inactive"):
            process_webhook_delivery_job(
                job_id="job-1",
                database_url=database_url,
                encryption_key=encryption_key,
                deliverer=WebhookDeliverer(
                    sender=never_called_sender,
                    url_policy=_public_policy(),
                ),
            )

        with session_scope(session_factory) as session:
            job = SqlAlchemyJobRepository(session).get("job-1")
            delivery = SqlAlchemyWebhookRepository(session).get_delivery("delivery-1")
        assert job is not None and job.status == "queued" and job.attempts == 0
        assert delivery is not None and delivery.final_status == "pending"


def test_process_webhook_delivery_job_marks_retry_pending_on_retryable_failure(
    tmp_path,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="webhook_delivery_retry_pending",
    ) as database_url:
        encryption_key = _fernet_key()
        _seed_webhook_job_context(
            database_url=database_url,
            encryption_key=encryption_key,
        )

        def sender(*, url: str, body: str, headers: dict[str, str], timeout: float):
            del url, body, headers, timeout
            return 503, "temporarily unavailable"

        payload = process_webhook_delivery_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=encryption_key,
            deliverer=WebhookDeliverer(
                sender=sender,
                url_policy=_public_policy(),
            ),
        )
        assert payload["retryable"] is True

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            delivery = SqlAlchemyWebhookRepository(session).get_delivery("delivery-1")
            job = SqlAlchemyJobRepository(session).get("job-1")
            outbox = SqlAlchemyJobOutboxRepository(session).get_for_job("job-1")
        assert delivery is not None and delivery.final_status == "retry_pending"
        assert delivery.attempt_number == 1
        assert job is not None and job.status == "retry_scheduled"
        assert job.scheduled_at is not None
        assert outbox is not None and outbox.status == "pending"
        assert outbox.available_at == job.scheduled_at


def test_webhook_retries_keep_exact_body_and_end_in_observable_failure(
    tmp_path,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="webhook_delivery_exhausted",
    ) as database_url:
        encryption_key = _fernet_key()
        _seed_webhook_job_context(
            database_url=database_url,
            encryption_key=encryption_key,
        )
        captured_bodies: list[str] = []

        def sender(*, url: str, body: str, headers: dict[str, str], timeout: float):
            del url, headers, timeout
            captured_bodies.append(body)
            return 503, "temporary secret=must-not-persist"

        deliverer = WebhookDeliverer(sender=sender, url_policy=_public_policy())
        for _attempt in range(2):
            retry_payload = process_webhook_delivery_job(
                job_id="job-1",
                database_url=database_url,
                encryption_key=encryption_key,
                deliverer=deliverer,
            )
            assert retry_payload["retryable"] is True

        payload = process_webhook_delivery_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=encryption_key,
            deliverer=deliverer,
        )

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            delivery = SqlAlchemyWebhookRepository(session).get_delivery("delivery-1")
            job = SqlAlchemyJobRepository(session).get("job-1")
        assert payload["retryable"] is False
        assert len(set(captured_bodies)) == 1
        assert delivery is not None and delivery.attempt_number == 3
        assert delivery.final_status == "failed"
        assert "must-not-persist" not in (delivery.response_body_snapshot or "")
        assert job is not None and job.status == "failed"
        assert job.error_snapshot == {
            "category": "delivery_failed",
            "message": "max_attempts_exhausted",
        }


def test_publish_document_status_matches_subscriptions_and_wildcards(tmp_path) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="webhook_delivery_publish",
    ) as database_url:
        encryption_key = _fernet_key()
        _seed_webhook_publish_context(
            database_url=database_url,
            encryption_key=encryption_key,
        )

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        fake_queue = _FakeQueue()

        with session_scope(session_factory) as session:
            service = WebhookService(
                webhook_repository=SqlAlchemyWebhookRepository(session),
                emitter_repository=SqlAlchemyEmitterRepository(
                    session,
                    EncryptedCertificateStore(encryption_key),
                ),
                job_repository=SqlAlchemyJobRepository(session),
                secret_store=EncryptedCertificateStore(encryption_key),
                queue=fake_queue,
                deliverer=WebhookDeliverer(),
                database_url=database_url,
                encryption_key=encryption_key,
            )
            created = service.publish_document_status(
                document=Document(
                    id="doc-42",
                    emitter_id="emitter-1",
                    external_id="erp-doc-42",
                    idempotency_key="idem-42",
                    document_type="factura",
                    payload_snapshot=None,
                    generated_xml=None,
                    signed_xml=None,
                    sifen_request_xml=None,
                    sifen_response_raw=None,
                    last_query_request_xml=None,
                    last_query_response_raw=None,
                    last_query_at=None,
                    cdc="01800123450001001001001012026042411234567891",
                    internal_status="approved",
                    sifen_status="approved",
                    sifen_result_code="0260",
                    sifen_result_message="ok",
                    created_at=_now(),
                    updated_at=_now(),
                )
            )

            deliveries = SqlAlchemyWebhookRepository(session).list_recent_deliveries(
                limit=20
            )
            jobs = SqlAlchemyJobRepository(session).list_recent(limit=20)

        assert len(created) == 3
        assert len(deliveries) == 3
        assert all(
            delivery.event_type == "document.approved" for delivery in deliveries
        )
        webhook_jobs = [job for job in jobs if job.job_type == "webhook.deliver"]
        assert len(webhook_jobs) == 3
        assert len(fake_queue.enqueued_job_ids) == 3


def test_process_webhook_delivery_job_propagates_worker_correlation_id(
    tmp_path,
    monkeypatch,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="webhook_delivery_worker_correlation",
    ) as database_url:
        encryption_key = _fernet_key()
        _seed_webhook_job_context(
            database_url=database_url,
            encryption_key=encryption_key,
        )

        class _FakeCurrentJob:
            meta = {"correlation_id": "corr-webhook-worker-1"}

        monkeypatch.setattr(
            "kilasifen.infrastructure.jobs.workers.get_current_job",
            lambda: _FakeCurrentJob(),
        )
        observability_calls = []
        monkeypatch.setattr(
            "kilasifen.infrastructure.jobs.workers.ensure_worker_observability",
            lambda: observability_calls.append("called"),
        )

        def sender(*, url: str, body: str, headers: dict[str, str], timeout: float):
            del url, body, headers, timeout
            return 200, "ok"

        payload = process_webhook_delivery_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=encryption_key,
            deliverer=WebhookDeliverer(sender=sender, url_policy=_public_policy()),
        )

        assert payload["job_status"] == "succeeded"
        assert observability_calls == ["called"]

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            job = SqlAlchemyJobRepository(session).get("job-1")

        assert job is not None
        assert job.worker_correlation_id == "corr-webhook-worker-1"


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
        request_body=None,
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
        SqlAlchemyEmitterRepository(session, store).save(emitter)
        webhook_repository = SqlAlchemyWebhookRepository(session)
        webhook_repository.save_endpoint(endpoint)
        webhook_repository.save_delivery(delivery)
        SqlAlchemyJobRepository(session).save(job)


def _seed_webhook_publish_context(*, database_url: str, encryption_key: str) -> None:
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
    endpoints = [
        WebhookEndpoint(
            id="endpoint-exact",
            emitter_id="emitter-1",
            url="https://erp.example.com/hooks/exact",
            secret_encrypted=store.encrypt_text("secret-1"),
            event_subscriptions=["document.approved"],
            is_active=True,
            retry_policy=None,
            created_at=_now(),
            updated_at=_now(),
        ),
        WebhookEndpoint(
            id="endpoint-wildcard",
            emitter_id="emitter-1",
            url="https://erp.example.com/hooks/wildcard",
            secret_encrypted=store.encrypt_text("secret-2"),
            event_subscriptions=["document.*"],
            is_active=True,
            retry_policy=None,
            created_at=_now(),
            updated_at=_now(),
        ),
        WebhookEndpoint(
            id="endpoint-all",
            emitter_id="emitter-1",
            url="https://erp.example.com/hooks/all",
            secret_encrypted=store.encrypt_text("secret-3"),
            event_subscriptions=None,
            is_active=True,
            retry_policy=None,
            created_at=_now(),
            updated_at=_now(),
        ),
        WebhookEndpoint(
            id="endpoint-non-match",
            emitter_id="emitter-1",
            url="https://erp.example.com/hooks/non-match",
            secret_encrypted=store.encrypt_text("secret-4"),
            event_subscriptions=["event.approved"],
            is_active=True,
            retry_policy=None,
            created_at=_now(),
            updated_at=_now(),
        ),
    ]

    with session_scope(session_factory) as session:
        SqlAlchemyEmitterRepository(session, store).save(emitter)
        repository = SqlAlchemyWebhookRepository(session)
        for endpoint in endpoints:
            repository.save_endpoint(endpoint)


class _FakeQueue:
    def __init__(self) -> None:
        self.enqueued_job_ids: list[str] = []

    def enqueue_webhook_delivery(self, job, *, database_url: str, encryption_key: str):
        del database_url, encryption_key
        self.enqueued_job_ids.append(job.id)
        return {"job_id": job.id}


def _now() -> datetime:
    return datetime.now(UTC)


def _fernet_key() -> str:
    return "4fV1_r04jQs6C1UNq9qS4RuCs1oQcWzER8GqW04A1lE="


def _public_policy() -> WebhookUrlPolicy:
    return WebhookUrlPolicy(resolver=lambda _host, _port: ["93.184.216.34"])
