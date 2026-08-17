from dataclasses import dataclass, replace
from datetime import UTC, date, datetime

import pytest

from kilasifen.config import get_settings
from kilasifen.domain.certificates.models import Certificate
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.jobs.models import Job
from kilasifen.domain.stampings.models import Stamping
from kilasifen.domain.webhooks.models import WebhookEndpoint
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
from kilasifen.infrastructure.db.repositories.webhooks import (
    SqlAlchemyWebhookRepository,
)
from kilasifen.infrastructure.db.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from kilasifen.infrastructure.jobs.workers import (
    DocumentEmissionRetryableError,
    process_document_job,
)
from kilasifen.infrastructure.sifen.engine import (
    EmissionOutcome,
    EmissionTransportUncertainError,
)
from kilasifen.infrastructure.sifen.query import DocumentQueryOutcome
from kilasifen.testing.database import managed_test_database_url
from pysifen.sdk.errors import (
    SifenRejectionError,
    SifenTimeoutError,
    SifenValidationError,
)


def test_process_document_job_persists_emission_artifacts(tmp_path) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_success",
    ) as database_url:
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)

        fake_engine = FakeEmissionEngine(
            outcome=EmissionOutcome(
                generated_xml="<rDE/>",
                signed_xml=(
                    '<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd">'
                    '<DE Id="0180012345"/>'
                    "<Signature/></rDE>"
                ),
                request_xml="<soap>request</soap>",
                response_raw="<soap>response</soap>",
                sifen_status="approved",
                result_code="0260",
                result_message="Autorizacion satisfactoria",
                cdc="0180012345",
            )
        )

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=fake_engine,
            current_date=date(2024, 4, 24),
        )

        assert payload["job_id"] == "job-1"
        assert payload["document_id"] == "document-1"
        assert payload["job_status"] == "succeeded"
        assert payload["document_status"] == "approved"

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            document = SqlAlchemyDocumentRepository(session).get("document-1")
            job = SqlAlchemyJobRepository(session).get("job-1")

        assert document is not None
        assert document.generated_xml == "<rDE/>"
        assert document.signed_xml is not None
        assert document.sifen_request_xml == "<soap>request</soap>"
        assert document.sifen_response_raw == "<soap>response</soap>"
        assert document.internal_status == "approved"
        assert document.cdc == "0180012345"
        assert document.sifen_result_code == "0260"
        assert job is not None
        assert job.status == "succeeded"
        assert job.error_snapshot is None


@pytest.mark.parametrize(
    ("error", "expected_job_status", "expected_document_status", "expected_category"),
    [
        (
            SifenValidationError("payload invalido"),
            "failed",
            "failed",
            "fiscal_validation",
        ),
        (
            SifenTimeoutError("timeout"),
            "retry_scheduled",
            "retry_pending",
            "transport",
        ),
        (
            SifenRejectionError("2500", "calculo-coincide-info-xml"),
            "failed",
            "rejected",
            "sifen_rejection",
        ),
    ],
)
def test_process_document_job_categorizes_failures(
    tmp_path,
    error,
    expected_job_status,
    expected_document_status,
    expected_category,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_failure",
    ) as database_url:
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)

        if expected_job_status == "retry_scheduled":
            with pytest.raises(DocumentEmissionRetryableError):
                process_document_job(
                    job_id="job-1",
                    database_url=database_url,
                    encryption_key=_fernet_key(),
                    emission_engine=FakeEmissionEngine(error=error),
                    current_date=date(2024, 4, 24),
                )
        else:
            payload = process_document_job(
                job_id="job-1",
                database_url=database_url,
                encryption_key=_fernet_key(),
                emission_engine=FakeEmissionEngine(error=error),
                current_date=date(2024, 4, 24),
            )
            assert payload["job_status"] == expected_job_status
            assert payload["document_status"] == expected_document_status

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            document = SqlAlchemyDocumentRepository(session).get("document-1")
            job = SqlAlchemyJobRepository(session).get("job-1")

        assert document is not None
        assert document.internal_status == expected_document_status
        assert job is not None
        assert job.status == expected_job_status
        assert job.error_snapshot is not None
        assert job.error_snapshot["category"] == expected_category


def test_process_document_job_publishes_webhook_events_when_enabled(
    tmp_path,
    monkeypatch,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_webhooks",
    ) as database_url:
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)
        _seed_webhook_endpoint(database_url=database_url, store=store)

        monkeypatch.setenv("KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS", "true")
        get_settings.cache_clear()

        fake_queue = FakeWebhookQueue()
        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=FakeEmissionEngine(
                outcome=EmissionOutcome(
                    generated_xml="<rDE/>",
                    signed_xml="<rDE><Signature/></rDE>",
                    request_xml="<soap>request</soap>",
                    response_raw="<soap>response</soap>",
                    sifen_status="approved",
                    result_code="0260",
                    result_message="Autorizacion satisfactoria",
                )
            ),
            current_date=date(2024, 4, 24),
            webhook_queue=fake_queue,
        )
        get_settings.cache_clear()

        assert payload["job_status"] == "succeeded"
        assert fake_queue.enqueued_job_ids

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            deliveries = SqlAlchemyWebhookRepository(session).list_recent_deliveries(
                limit=10
            )
            delivery_jobs = SqlAlchemyJobRepository(session).list_recent(limit=10)

        assert len(deliveries) == 1
        assert deliveries[0].event_type == "document.approved"
        webhook_jobs = [
            job for job in delivery_jobs if job.job_type == "webhook.deliver"
        ]
        assert len(webhook_jobs) == 1
        assert webhook_jobs[0].status == "queued"


def test_process_document_job_propagates_worker_correlation_id(
    tmp_path,
    monkeypatch,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_worker_correlation",
    ) as database_url:
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)

        class _FakeCurrentJob:
            meta = {"correlation_id": "corr-worker-1"}

        monkeypatch.setattr(
            "kilasifen.infrastructure.jobs.workers.get_current_job",
            lambda: _FakeCurrentJob(),
        )
        observability_calls = []
        monkeypatch.setattr(
            "kilasifen.infrastructure.jobs.workers.ensure_worker_observability",
            lambda: observability_calls.append("called"),
        )

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=FakeEmissionEngine(
                outcome=EmissionOutcome(
                    generated_xml="<rDE/>",
                    signed_xml=(
                        '<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd">'
                        '<DE Id="0180012345"/>'
                        "<Signature/></rDE>"
                    ),
                    request_xml="<soap>request</soap>",
                    response_raw="<soap>response</soap>",
                    sifen_status="approved",
                    result_code="0260",
                    result_message="Autorizacion satisfactoria",
                    cdc="0180012345",
                )
            ),
            current_date=date(2024, 4, 24),
        )

        assert payload["job_status"] == "succeeded"
        assert observability_calls == ["called"]

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            job = SqlAlchemyJobRepository(session).get("job-1")

        assert job is not None
        assert job.worker_correlation_id == "corr-worker-1"


def test_process_document_job_marks_rejected_outcome_without_engine_exception(
    tmp_path,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_rejected_outcome",
    ) as database_url:
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=FakeEmissionEngine(
                outcome=EmissionOutcome(
                    generated_xml="<rDE/>",
                    signed_xml=(
                        '<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd">'
                        '<DE Id="0180099999"/>'
                        "<Signature/></rDE>"
                    ),
                    request_xml="<soap>request</soap>",
                    response_raw="<soap>response</soap>",
                    sifen_status="rejected",
                    result_code="1330",
                    result_message=(
                        "Es obligatorio informar el numero de casa del receptor"
                    ),
                    cdc="0180099999",
                )
            ),
            current_date=date(2024, 4, 24),
        )

        assert payload["job_status"] == "failed"
        assert payload["document_status"] == "rejected"

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            document = SqlAlchemyDocumentRepository(session).get("document-1")
            job = SqlAlchemyJobRepository(session).get("job-1")

        assert document is not None
        assert document.internal_status == "rejected"
        assert document.cdc == "0180099999"
        assert job is not None
        assert job.status == "failed"
        assert job.error_snapshot is not None
        assert job.error_snapshot["category"] == "sifen_rejection"


def test_process_document_job_keeps_submitted_outcome_reconcilable(tmp_path) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_submitted_outcome",
    ) as database_url:
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)

        with pytest.raises(DocumentEmissionRetryableError):
            process_document_job(
                job_id="job-1",
                database_url=database_url,
                encryption_key=_fernet_key(),
                emission_engine=FakeEmissionEngine(
                    outcome=EmissionOutcome(
                        generated_xml="<rDE/>",
                        signed_xml=(
                            '<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd">'
                            '<DE Id="0180012345"/><Signature/></rDE>'
                        ),
                        request_xml="<soap>request</soap>",
                        response_raw="<soap>response</soap>",
                        sifen_status="submitted",
                        result_code="0300",
                        result_message="Procesamiento pendiente",
                        cdc="0180012345",
                    )
                ),
                current_date=date(2024, 4, 24),
            )

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            job = SqlAlchemyJobRepository(session).get("job-1")
        assert job is not None
        assert job.status == "retry_scheduled"
        assert job.error_snapshot == {
            "category": "sifen_pending",
            "code": "0300",
            "message": "Procesamiento pendiente",
        }


def test_transport_uncertainty_persists_exact_payload_before_retry(tmp_path) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_transport_uncertain",
    ) as database_url:
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)
        error = EmissionTransportUncertainError(
            "timeout after send",
            generated_xml="<rDE/>",
            signed_xml='<rDE><DE Id="0180012345"/><Signature/></rDE>',
            request_xml="<soap>request</soap>",
            cdc="0180012345",
        )

        with pytest.raises(DocumentEmissionRetryableError):
            process_document_job(
                job_id="job-1",
                database_url=database_url,
                encryption_key=_fernet_key(),
                emission_engine=FakeEmissionEngine(error=error),
                current_date=date(2024, 4, 24),
            )

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            document = SqlAlchemyDocumentRepository(session).get("document-1")
        assert document is not None
        assert document.internal_status == "retry_pending"
        assert document.cdc == "0180012345"
        assert document.signed_xml == error.signed_xml


def test_retry_queries_cdc_and_does_not_resubmit_when_sifen_has_document(
    tmp_path,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_reconcile_before_retry",
    ) as database_url:
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            documents = SqlAlchemyDocumentRepository(session)
            jobs = SqlAlchemyJobRepository(session)
            document = documents.get("document-1")
            job = jobs.get("job-1")
            assert document is not None and job is not None
            documents.save(
                replace(
                    document,
                    internal_status="retry_pending",
                    cdc="0180012345",
                    signed_xml='<rDE><DE Id="0180012345"/><Signature/></rDE>',
                )
            )
            jobs.save(replace(job, status="retry_scheduled", attempts=1))

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=FakeEmissionEngine(
                error=AssertionError("document must not be resubmitted")
            ),
            query_gateway=FakeQueryGateway(),
            current_date=date(2024, 4, 24),
        )

        assert payload["document_status"] == "approved"
        assert payload["job_status"] == "succeeded"


@dataclass
class FakeEmissionEngine:
    outcome: EmissionOutcome | None = None
    error: Exception | None = None

    def emit_document(self, **kwargs) -> EmissionOutcome:
        del kwargs
        if self.error is not None:
            raise self.error
        assert self.outcome is not None
        return self.outcome


@dataclass
class FakeQueryGateway:
    def query_document(self, **kwargs) -> DocumentQueryOutcome:
        del kwargs
        return DocumentQueryOutcome(
            cdc="0180012345",
            request_xml="<query/>",
            response_raw="<found/>",
            result_code="0422",
            result_message="CDC encontrado y aprobado",
            status="found",
            content_xml='<rDE><DE Id="0180012345"/><Signature/></rDE>',
            processed_at=None,
        )


class FakeWebhookQueue:
    def __init__(self) -> None:
        self.enqueued_job_ids: list[str] = []

    def enqueue_webhook_delivery(self, job, *, database_url: str, encryption_key: str):
        del database_url, encryption_key
        self.enqueued_job_ids.append(job.id)
        return {"job_id": job.id}


def _seed_emission_context(database_url: str, store: EncryptedCertificateStore) -> None:
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)

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
        start_date=date(2024, 3, 11),
        end_date=None,
        is_active=True,
        status="active",
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
        SqlAlchemyEmitterRepository(session, store).save(emitter)
        SqlAlchemyCertificateRepository(session).save(certificate)
        SqlAlchemyStampingRepository(session).save(stamping)
        SqlAlchemyDocumentRepository(session).save(document)
        SqlAlchemyJobRepository(session).save(job)


def _seed_webhook_endpoint(
    *,
    database_url: str,
    store: EncryptedCertificateStore,
) -> None:
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
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
    with session_scope(session_factory) as session:
        SqlAlchemyWebhookRepository(session).save_endpoint(endpoint)


def _fernet_key() -> str:
    return "4fV1_r04jQs6C1UNq9qS4RuCs1oQcWzER8GqW04A1lE="


def _now() -> datetime:
    return datetime.now(UTC)
