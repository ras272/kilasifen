from dataclasses import dataclass
from datetime import UTC, datetime

import fakeredis
from rq import Queue

from kilasifen.domain.certificates.models import Certificate
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.jobs.models import Job
from kilasifen.domain.stampings.models import Stamping
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.repositories.certificates import (
    SqlAlchemyCertificateRepository,
)
from kilasifen.infrastructure.db.repositories.documents import (
    SqlAlchemyDocumentRepository,
)
from kilasifen.infrastructure.db.repositories.emitters import (
    SqlAlchemyEmitterRepository,
)
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.repositories.stampings import (
    SqlAlchemyStampingRepository,
)
from kilasifen.infrastructure.db.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from kilasifen.infrastructure.jobs.queue import RqJobQueue
from kilasifen.infrastructure.jobs.workers import process_document_job
from kilasifen.infrastructure.sifen.engine import EmissionOutcome
from kilasifen.logging import reset_correlation_id, set_correlation_id
from kilasifen.testing.database import managed_test_database_url


def test_rq_queue_enqueues_document_job_with_expected_payload() -> None:
    queue = Queue("documents", connection=fakeredis.FakeRedis())
    adapter = RqJobQueue(queue)

    job = Job(
        id="job-1",
        emitter_id="emitter-1",
        related_entity_type="document",
        related_entity_id="document-1",
        job_type="document.emit",
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

    token = set_correlation_id("corr-123")
    try:
        enqueued = adapter.enqueue_document_emit(
            job,
            database_url="postgresql+psycopg://postgres:postgres@localhost:5432/kilasifen",
            encryption_key=_fernet_key(),
        )
    finally:
        reset_correlation_id(token)

    assert (
        enqueued.func_name
        == "kilasifen.infrastructure.jobs.workers.process_document_job"
    )
    assert enqueued.kwargs["job_id"] == "job-1"
    assert set(enqueued.kwargs) == {"job_id"}
    assert "encryption_key" not in str(enqueued.data)
    assert "postgresql+psycopg" not in str(enqueued.data)
    assert enqueued.meta["correlation_id"] == "corr-123"
    assert enqueued.retries_left == 4
    assert enqueued.retry_intervals == [30, 120, 600, 1800]


def test_process_document_job_hydrates_job_and_document_context(tmp_path) -> None:
    with managed_test_database_url(tmp_path=tmp_path, name="rq_worker") as database_url:
        engine = build_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = build_session_factory(engine)
        store = EncryptedCertificateStore(_fernet_key())

        emitter = Emitter(
            id="emitter-1",
            external_id="erp-ares",
            ruc="80024135",
            dv="5",
            legal_name="ARES PARAGUAY SRL",
            tax_environment="test",
            status="active",
            csc=None,
            csc_id=None,
            created_at=_now(),
            updated_at=_now(),
        )
        document = Document(
            id="document-1",
            emitter_id="emitter-1",
            external_id="erp-doc-1",
            idempotency_key="idem-1",
            document_type="factura",
            payload_snapshot={"generated_xml": "<rDE/>", "doc_id": "0180012345"},
            generated_xml=None,
            signed_xml=None,
            sifen_request_xml=None,
            sifen_response_raw=None,
            last_query_request_xml=None,
            last_query_response_raw=None,
            last_query_at=None,
            cdc=None,
            internal_status="queued",
            sifen_status=None,
            sifen_result_code=None,
            sifen_result_message=None,
            created_at=_now(),
            updated_at=_now(),
        )
        certificate = Certificate(
            id="cert-1",
            emitter_id="emitter-1",
            logical_name="principal",
            encrypted_p12=store.encrypt_bytes(b"fake-cert"),
            encrypted_password=store.encrypt_text("secret"),
            fingerprint="fingerprint",
            serial_number=None,
            subject_summary=None,
            detected_ruc="80024135",
            valid_from=None,
            valid_until=None,
            is_active=True,
            status="uploaded",
            created_at=_now(),
            updated_at=_now(),
        )
        stamping = Stamping(
            id="stamp-1",
            emitter_id="emitter-1",
            number="80024135",
            start_date=datetime(2024, 3, 11, tzinfo=UTC).date(),
            end_date=None,
            is_active=True,
            status="active",
            created_at=_now(),
            updated_at=_now(),
        )
        job = Job(
            id="job-1",
            emitter_id="emitter-1",
            related_entity_type="document",
            related_entity_id="document-1",
            job_type="document.emit",
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
            SqlAlchemyCertificateRepository(session).save(certificate)
            SqlAlchemyStampingRepository(session).save(stamping)
            SqlAlchemyDocumentRepository(session).save(document)
            SqlAlchemyJobRepository(session).save(job)

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=FakeEmissionEngine(
                EmissionOutcome(
                    generated_xml="<rDE/>",
                    signed_xml="<rDE><Signature/></rDE>",
                    request_xml="<soap>request</soap>",
                    response_raw="<soap>response</soap>",
                    sifen_status="approved",
                    result_code="0260",
                    result_message="ok",
                )
            ),
            current_date=datetime(2024, 4, 24, tzinfo=UTC).date(),
        )

        assert payload["job_id"] == "job-1"
        assert payload["document_id"] == "document-1"
        assert payload["document_type"] == "factura"
        assert payload["job_type"] == "document.emit"
        assert payload["job_status"] == "succeeded"
        assert payload["document_status"] == "approved"


def test_rq_queue_enqueues_webhook_delivery_with_correlation_id() -> None:
    queue = Queue("webhooks", connection=fakeredis.FakeRedis())
    adapter = RqJobQueue(queue)
    job = Job(
        id="job-webhook-1",
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

    token = set_correlation_id("corr-webhook-1")
    try:
        enqueued = adapter.enqueue_webhook_delivery(
            job,
            database_url="postgresql+psycopg://postgres:postgres@localhost:5432/kilasifen",
            encryption_key=_fernet_key(),
        )
    finally:
        reset_correlation_id(token)

    assert (
        enqueued.func_name
        == "kilasifen.infrastructure.jobs.workers.process_webhook_delivery_job"
    )
    assert enqueued.meta["correlation_id"] == "corr-webhook-1"
    assert set(enqueued.kwargs) == {"job_id"}
    assert "encryption_key" not in str(enqueued.data)
    assert "postgresql+psycopg" not in str(enqueued.data)
    assert enqueued.retries_left == 7
    assert enqueued.retry_intervals == [10, 30, 120, 300, 900, 1800, 3600]


@dataclass
class FakeEmissionEngine:
    outcome: EmissionOutcome

    def emit_document(self, **kwargs) -> EmissionOutcome:
        return self.outcome


def _fernet_key() -> str:
    return "4fV1_r04jQs6C1UNq9qS4RuCs1oQcWzER8GqW04A1lE="


def _now() -> datetime:
    return datetime.now(UTC)
