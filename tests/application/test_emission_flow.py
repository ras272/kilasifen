from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from kilasifen.config import get_settings
from kilasifen.domain.certificates.models import Certificate
from kilasifen.domain.common.errors import ConflictError
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.jobs.models import Job
from kilasifen.domain.stampings.models import Stamping
from kilasifen.domain.webhooks.models import WebhookEndpoint
from kilasifen.engine.sdk.errors import (
    SifenRejectionError,
    SifenTimeoutError,
    SifenValidationError,
)
from kilasifen.engine.sdk.signer import clear_pkcs12_signer_cache, get_pkcs12_signer
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.models import CertificateModel, EmitterModel
from kilasifen.infrastructure.db.repositories.certificates import (
    SqlAlchemyCertificateRepository,
)
from kilasifen.infrastructure.db.repositories.documents import (
    SqlAlchemyDocumentRepository,
)
from kilasifen.infrastructure.db.repositories.emitters import (
    SqlAlchemyEmitterRepository,
)
from kilasifen.infrastructure.db.repositories.job_outbox import (
    SqlAlchemyJobOutboxRepository,
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
from kilasifen.infrastructure.jobs.workers import process_document_job
from kilasifen.infrastructure.sifen.engine import (
    PreparedSubmission,
    SubmissionOutcome,
)
from kilasifen.infrastructure.sifen.query import (
    QUERY_ERROR,
    QUERY_FOUND,
    QUERY_NOT_FOUND_OR_NOT_APPROVED,
    DocumentQueryOutcome,
)
from kilasifen.testing.database import managed_test_database_url


def test_process_document_job_persists_emission_artifacts(tmp_path) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_success",
    ) as database_url:
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)

        fake_engine = FakeEmissionEngine(
            **_answer(
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


def test_completed_document_job_drops_cached_signing_keys(tmp_path) -> None:
    pfx = (Path(__file__).resolve().parents[1] / "test_cert.pfx").read_bytes()
    clear_pkcs12_signer_cache()
    cached_signer = get_pkcs12_signer(pfx, "test1234")
    try:
        with managed_test_database_url(
            tmp_path=tmp_path,
            name="emission_drops_signers",
        ) as database_url:
            _seed_emission_context(
                database_url, EncryptedCertificateStore(_fernet_key())
            )

            payload = process_document_job(
                job_id="job-1",
                database_url=database_url,
                encryption_key=_fernet_key(),
                emission_engine=FakeEmissionEngine(
                    prepare_error=SifenValidationError("payload invalido")
                ),
                current_date=date(2024, 4, 24),
            )

        assert payload["job_status"] == "failed"
        assert get_pkcs12_signer(pfx, "test1234") is not cached_signer
    finally:
        clear_pkcs12_signer_cache()


def test_queued_document_job_honors_inactive_emitter_before_secret_access(
    tmp_path,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="inactive_emitter_worker",
    ) as database_url:
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            emitter = session.get(EmitterModel, "emitter-1")
            certificate = session.get(CertificateModel, "cert-1")
            assert emitter is not None and certificate is not None
            emitter.status = "inactive"
            emitter.csc = "invalid-ciphertext-must-not-be-decrypted"
            certificate.encrypted_p12 = "invalid-ciphertext-must-not-be-decrypted"
            certificate.encrypted_password = "invalid-ciphertext-must-not-be-decrypted"

        class NeverCalledEmissionEngine:
            def prepare_document(self, **kwargs):
                del kwargs
                raise AssertionError(
                    "inactive emitter reached the SIFEN emission engine"
                )

            submit_prepared = prepare_document

        with pytest.raises(ConflictError, match="emitters.inactive"):
            process_document_job(
                job_id="job-1",
                database_url=database_url,
                encryption_key=_fernet_key(),
                emission_engine=NeverCalledEmissionEngine(),
                current_date=date(2024, 4, 24),
            )

        with session_scope(session_factory) as session:
            job = SqlAlchemyJobRepository(session).get("job-1")
            document = SqlAlchemyDocumentRepository(session).get("document-1")
        assert job is not None and job.status == "queued" and job.attempts == 0
        assert document is not None and document.internal_status == "queued"


@pytest.mark.parametrize(
    ("engine", "expected_job_status", "expected_document_status", "expected_category"),
    [
        (
            lambda: FakeEmissionEngine(
                prepare_error=SifenValidationError("payload invalido")
            ),
            "failed",
            "failed",
            "fiscal_validation",
        ),
        (
            lambda: FakeEmissionEngine(submit_error=SifenTimeoutError("timeout")),
            "retry_scheduled",
            "retry_pending",
            "transport",
        ),
        (
            lambda: FakeEmissionEngine(
                submit_error=SifenRejectionError("2500", "calculo-coincide-info-xml")
            ),
            "failed",
            "rejected",
            "sifen_rejection",
        ),
    ],
)
def test_process_document_job_categorizes_failures(
    tmp_path,
    engine,
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

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=engine(),
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
                **_answer(
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
                **_answer(
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
                **_answer(
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


def test_an_unclassified_answer_is_reconciled_not_rejected(tmp_path) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_submitted_outcome",
    ) as database_url:
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=FakeEmissionEngine(
                **_answer(
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
        assert payload["job_status"] == "retry_scheduled"

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            job = SqlAlchemyJobRepository(session).get("job-1")
            outbox = SqlAlchemyJobOutboxRepository(session).get_for_job("job-1")
        assert job is not None
        assert job.status == "retry_scheduled"
        assert job.scheduled_at is not None
        assert outbox is not None
        assert outbox.status == "pending"
        assert outbox.available_at == job.scheduled_at
        assert job.error_snapshot == {
            "category": "sifen_unclassified",
            "code": "0300",
            "message": "Procesamiento pendiente",
        }
        # DECISIONES F60: without a recognizable dEstRes the CDC is queried.
        assert payload["document_status"] == "retry_pending"


def test_transport_uncertainty_persists_exact_payload_before_retry(tmp_path) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_transport_uncertain",
    ) as database_url:
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)
        engine = FakeEmissionEngine(
            submit_error=SifenTimeoutError("timeout after send")
        )

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=engine,
            current_date=date(2024, 4, 24),
        )
        assert payload["job_status"] == "retry_scheduled"

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            document = SqlAlchemyDocumentRepository(session).get("document-1")
        assert document is not None
        assert document.internal_status == "retry_pending"
        assert document.cdc == "0180012345"
        assert document.signed_xml == _PREPARED.signed_xml
        assert document.sifen_request_xml == _PREPARED.request_xml


def test_retry_queries_cdc_and_does_not_resubmit_when_sifen_has_document(
    tmp_path,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_reconcile_before_retry",
    ) as database_url:
        never_resubmitted = FakeEmissionEngine()
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
                    sifen_request_xml="<emit-request/>",
                    sifen_response_raw="<emit-response/>",
                )
            )
            jobs.save(replace(job, status="retry_scheduled", attempts=1))

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=never_resubmitted,
            query_gateway=FakeQueryGateway(),
            current_date=date(2024, 4, 24),
        )

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            document = SqlAlchemyDocumentRepository(session).get("document-1")
            job = SqlAlchemyJobRepository(session).get("job-1")

        assert payload["document_status"] == "approved"
        assert payload["job_status"] == "succeeded"
        assert never_resubmitted.calls == []
        assert document is not None
        assert document.sifen_request_xml == "<emit-request/>"
        assert document.sifen_response_raw == "<emit-response/>"
        assert document.last_query_request_xml == "<query/>"
        assert document.last_query_response_raw == "<found/>"
        assert document.last_query_at is not None
        assert job is not None


def test_a_cdc_sifen_does_not_approve_is_queued_and_resent_as_signed(
    tmp_path,
) -> None:
    """DECISIONES F63: query first; with 0420 the same signed DE travels again.

    Dto 872/2023 Art. 29 and MT v150 §6.5 (pp. 26-27) allow the same CDC to
    be sent again; the Guia MP oct-2024 (p. 12) asks for it after 0420.
    """

    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_not_approved_resend",
    ) as database_url:
        engine_double = FakeEmissionEngine(
            outcome=SubmissionOutcome(
                response_raw="<approved/>",
                sifen_status="approved",
                result_code="0260",
                result_message="Autorizacion satisfactoria",
            )
        )
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)
        _seed_retry_pending_document(database_url, attempts=1)

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=engine_double,
            query_gateway=FakeQueryGateway(status=QUERY_NOT_FOUND_OR_NOT_APPROVED),
            current_date=date(2024, 4, 24),
        )
        assert payload["job_status"] == "retry_scheduled"
        assert payload["document_status"] == "queued"
        assert engine_double.calls == []

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            document = SqlAlchemyDocumentRepository(session).get("document-1")
            job = SqlAlchemyJobRepository(session).get("job-1")

        assert document is not None
        assert document.cdc == "0180012345"
        assert document.signed_xml == (
            '<rDE><DE Id="0180012345"/><Signature/></rDE>'
        )
        assert document.last_query_request_xml == "<query/>"
        assert document.last_query_response_raw == "<not-found/>"
        assert job is not None
        assert job.attempts == 2
        assert job.error_snapshot == {
            "category": "resubmission",
            "code": "0420",
            "message": "CDC no encontrado o no aprobado",
        }

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=engine_double,
            query_gateway=FakeQueryGateway(status=QUERY_NOT_FOUND_OR_NOT_APPROVED),
            current_date=date(2024, 4, 24),
        )

        with session_scope(session_factory) as session:
            document = SqlAlchemyDocumentRepository(session).get("document-1")
        assert payload["document_status"] == "approved"
        # Never re-signed: the stored signed DE in a new rEnviDe (new dId).
        assert engine_double.calls == ["wrap", "submit"]
        assert engine_double.wrapped == [document.signed_xml]
        assert engine_double.submitted_requests == [document.sifen_request_xml]
        assert document.sifen_request_xml != "<emit-request/>"


def test_a_query_error_is_not_an_answer_on_the_cdc(tmp_path) -> None:
    """0421 and any code but 0420/0422 keep querying (DECISIONES F62)."""

    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_query_error",
    ) as database_url:
        never_resubmitted = FakeEmissionEngine()
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)
        _seed_retry_pending_document(database_url, attempts=1)

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=never_resubmitted,
            query_gateway=FakeQueryGateway(status=QUERY_ERROR),
            current_date=date(2024, 4, 24),
        )

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            document = SqlAlchemyDocumentRepository(session).get("document-1")
            job = SqlAlchemyJobRepository(session).get("job-1")

        assert payload["document_status"] == "retry_pending"
        assert never_resubmitted.calls == []
        assert document is not None and job is not None
        assert document.sifen_request_xml == "<emit-request/>"
        assert job.error_snapshot == {
            "category": "reconciliation_pending",
            "code": "0421",
            "message": "RUC Certificado sin permiso",
        }


def test_an_unanswered_cdc_after_the_retry_budget_requires_reconciliation(
    tmp_path,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_reconciliation_required",
    ) as database_url:
        never_resubmitted = FakeEmissionEngine()
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)
        _seed_retry_pending_document(database_url, attempts=4)

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=never_resubmitted,
            query_gateway=FakeQueryGateway(status=QUERY_ERROR),
            current_date=date(2024, 4, 24),
        )

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            document = SqlAlchemyDocumentRepository(session).get("document-1")
            job = SqlAlchemyJobRepository(session).get("job-1")

        assert payload["document_status"] == "reconciliation_required"
        assert payload["job_status"] == "failed"
        assert never_resubmitted.calls == []
        assert document is not None
        assert document.internal_status == "reconciliation_required"
        assert document.cdc == "0180012345"
        assert document.last_query_response_raw == "<error/>"
        assert job is not None
        assert job.attempts == 5
        assert job.error_snapshot == {
            "category": "reconciliation_required",
            "code": "0421",
            "message": (
                "automatic attempts exhausted while SIFEN's answer for the CDC "
                "is unknown; an operator retry queries the CDC again"
            ),
        }


def test_a_cdc_not_approved_on_the_last_attempt_waits_queued_for_a_retry(
    tmp_path,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_not_approved_budget",
    ) as database_url:
        never_resubmitted = FakeEmissionEngine()
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)
        _seed_retry_pending_document(database_url, attempts=4)

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=never_resubmitted,
            query_gateway=FakeQueryGateway(status=QUERY_NOT_FOUND_OR_NOT_APPROVED),
            current_date=date(2024, 4, 24),
        )

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            job = SqlAlchemyJobRepository(session).get("job-1")

        assert payload["document_status"] == "queued"
        assert payload["job_status"] == "failed"
        assert never_resubmitted.calls == []
        assert job is not None
        assert job.error_snapshot["category"] == "retry_exhausted"


def test_requeued_reconciliation_required_document_still_cannot_be_resubmitted(
    tmp_path,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_reconciliation_hard_barrier",
    ) as database_url:
        never_resubmitted = FakeEmissionEngine()
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)
        _seed_retry_pending_document(database_url, attempts=5)

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            documents = SqlAlchemyDocumentRepository(session)
            jobs = SqlAlchemyJobRepository(session)
            stampings = SqlAlchemyStampingRepository(session)
            document = documents.get("document-1")
            job = jobs.get("job-1")
            assert document is not None and job is not None
            documents.save(
                replace(
                    document,
                    internal_status="reconciliation_required",
                    sifen_status="reconciliation_required",
                )
            )
            jobs.save(replace(job, status="queued"))
            stamping = stampings.get_active_for_emitter(
                "emitter-1",
                on_date=date(2024, 4, 24),
            )
            assert stamping is not None
            stampings.save(replace(stamping, is_active=False))

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=never_resubmitted,
            query_gateway=FakeQueryGateway(status="found"),
            current_date=date(2024, 4, 24),
        )

        assert payload["document_status"] == "approved"
        assert payload["job_status"] == "succeeded"
        assert never_resubmitted.calls == []


def _raw_document_issued_on(database_url: str, issued_at: str) -> None:
    """Make document-1 a raw DE whose dFeEmiDE is ``issued_at``."""

    generated_xml = (
        '<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd"><DE Id="0180012345">'
        f"<gDatGralOpe><dFeEmiDE>{issued_at}</dFeEmiDE></gDatGralOpe>"
        "</DE></rDE>"
    )
    session_factory = build_session_factory(build_engine(database_url))
    with session_scope(session_factory) as session:
        documents = SqlAlchemyDocumentRepository(session)
        document = documents.get("document-1")
        assert document is not None
        documents.save(
            replace(
                document,
                payload_snapshot={
                    "generated_xml": generated_xml,
                    "doc_id": "0180012345",
                },
            )
        )


def test_the_timbrado_is_chosen_with_the_emission_date_not_the_server_date(
    tmp_path,
) -> None:
    """DECISIONES F23: D002 picks the timbrado (1103/1104, MT v150 p. 160)."""

    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_timbrado_by_d002",
    ) as database_url:
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)
        session_factory = build_session_factory(build_engine(database_url))
        with session_scope(session_factory) as session:
            stampings = SqlAlchemyStampingRepository(session)
            first = stampings.get("stamp-1")
            assert first is not None
            stampings.save(replace(first, end_date=date(2024, 4, 10)))
            stampings.save(
                replace(
                    first,
                    id="stamp-2",
                    number="80024199",
                    start_date=date(2024, 4, 11),
                    end_date=None,
                )
            )
        _raw_document_issued_on(database_url, "2024-04-01T10:00:00")
        engine_double = FakeEmissionEngine(
            outcome=SubmissionOutcome(
                response_raw="<approved/>",
                sifen_status="approved",
                result_code="0260",
                result_message="Autorizacion satisfactoria",
            )
        )

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=engine_double,
            # The server date falls in the second timbrado; D002 does not.
            current_date=date(2024, 4, 24),
        )

        with session_scope(session_factory) as session:
            document = SqlAlchemyDocumentRepository(session).get("document-1")
        assert payload["document_status"] == "approved"
        assert [stamping.id for stamping in engine_double.stampings] == ["stamp-1"]
        assert document is not None and document.timbrado == "80024135"


def test_an_emission_date_before_the_timbrado_is_refused_locally(tmp_path) -> None:
    """D002 before the timbrado start: SIFEN 1103 (NT 01), refused before."""

    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emission_before_timbrado",
    ) as database_url:
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)
        _raw_document_issued_on(database_url, "2024-03-01T10:00:00")
        never_prepared = FakeEmissionEngine()

        payload = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            emission_engine=never_prepared,
            current_date=date(2024, 4, 24),
        )

        session_factory = build_session_factory(build_engine(database_url))
        with session_scope(session_factory) as session:
            job = SqlAlchemyJobRepository(session).get("job-1")
        assert payload["document_status"] == "failed"
        assert never_prepared.calls == []
        assert job is not None
        assert job.error_snapshot["category"] == "fiscal_validation"
        assert "2024-03-01" in job.error_snapshot["message"]
        assert "1103" in job.error_snapshot["message"]


_PREPARED = PreparedSubmission(
    generated_xml="<rDE/>",
    signed_xml='<rDE><DE Id="0180012345"/><Signature/></rDE>',
    request_xml="<rEnviDe><dId>101</dId></rEnviDe>",
    cdc="0180012345",
)


@dataclass
class FakeEmissionEngine:
    """Two-step engine double; ``calls`` records which steps ran."""

    prepared: PreparedSubmission = _PREPARED
    outcome: SubmissionOutcome | None = None
    prepare_error: Exception | None = None
    submit_error: BaseException | None = None
    during_submit: Callable[[], None] | None = None
    calls: list[str] = field(default_factory=list)
    submitted_requests: list[str] = field(default_factory=list)
    wrapped: list[str] = field(default_factory=list)
    stampings: list[Stamping] = field(default_factory=list)

    def prepare_document(self, *, stamping: Stamping, **kwargs) -> PreparedSubmission:
        del kwargs
        self.calls.append("prepare")
        self.stampings.append(stamping)
        if self.prepare_error is not None:
            raise self.prepare_error
        return self.prepared

    def wrap_signed_document(self, *, signed_xml: str) -> str:
        """A new rEnviDe (new dId) around the same signed DE."""

        self.calls.append("wrap")
        self.wrapped.append(signed_xml)
        return f"<rEnviDe><dId>{900 + len(self.wrapped)}</dId>{signed_xml}</rEnviDe>"

    def submit_prepared(self, *, request_xml: str, **kwargs) -> SubmissionOutcome:
        del kwargs
        self.calls.append("submit")
        self.submitted_requests.append(request_xml)
        if self.during_submit is not None:
            self.during_submit()
        if self.submit_error is not None:
            raise self.submit_error
        assert self.outcome is not None
        return self.outcome


def _answer(
    *,
    generated_xml: str,
    signed_xml: str,
    request_xml: str,
    response_raw: str,
    sifen_status: str,
    result_code: str,
    result_message: str,
    cdc: str = "0180012345",
) -> dict:
    """Engine double settings: what gets prepared and how SIFEN answers."""

    return {
        "prepared": PreparedSubmission(
            generated_xml=generated_xml,
            signed_xml=signed_xml,
            request_xml=request_xml,
            cdc=cdc,
        ),
        "outcome": SubmissionOutcome(
            response_raw=response_raw,
            sifen_status=sifen_status,
            result_code=result_code,
            result_message=result_message,
        ),
    }


@dataclass
class FakeQueryGateway:
    """siConsDE double: ``status`` is one of the gateway statuses."""

    status: str = QUERY_FOUND
    container: object | None = None

    def query_document(self, **kwargs) -> DocumentQueryOutcome:
        del kwargs
        if self.status == QUERY_NOT_FOUND_OR_NOT_APPROVED:
            return DocumentQueryOutcome(
                cdc="0180012345",
                request_xml="<query/>",
                response_raw="<not-found/>",
                result_code="0420",
                result_message="CDC no encontrado o no aprobado",
                status=QUERY_NOT_FOUND_OR_NOT_APPROVED,
                content_xml=None,
                processed_at=None,
            )
        if self.status == QUERY_ERROR:
            return DocumentQueryOutcome(
                cdc="0180012345",
                request_xml="<query/>",
                response_raw="<error/>",
                result_code="0421",
                result_message="RUC Certificado sin permiso",
                status=QUERY_ERROR,
                content_xml=None,
                processed_at=None,
            )
        return DocumentQueryOutcome(
            cdc="0180012345",
            request_xml="<query/>",
            response_raw="<found/>",
            result_code="0422",
            result_message="CDC encontrado y aprobado",
            status=QUERY_FOUND,
            content_xml="<rContDe/>",
            processed_at=None,
            container=self.container,
        )


def _seed_retry_pending_document(database_url: str, *, attempts: int) -> None:
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
                sifen_status="retry_pending",
                cdc="0180012345",
                generated_xml="<rDE/>",
                signed_xml='<rDE><DE Id="0180012345"/><Signature/></rDE>',
                sifen_request_xml="<emit-request/>",
                sifen_response_raw="<emit-response/>",
            )
        )
        jobs.save(replace(job, status="retry_scheduled", attempts=attempts))


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
    return datetime.now(timezone.utc)
