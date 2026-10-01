"""SIFEN queries run without row locks and decide on the committed document."""

import os
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from kilasifen.application.queries.service import QueryService
from kilasifen.domain.certificates.models import Certificate
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.jobs.models import Job
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.models import EmitterModel
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
from kilasifen.infrastructure.db.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from kilasifen.infrastructure.sifen.query import DocumentQueryOutcome
from kilasifen.testing.database import managed_test_database_url

_CDC = "01800241355001001000000012026042711234567893"


@pytest.fixture
def database_url(tmp_path: Path) -> Iterator[str]:
    with managed_test_database_url(tmp_path=tmp_path, name="query_locks") as url:
        yield url


@pytest.fixture
def store() -> EncryptedCertificateStore:
    return EncryptedCertificateStore(Fernet.generate_key().decode())


def test_document_query_never_locks_the_emitter(
    database_url: str,
    store: EncryptedCertificateStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = _seed(database_url, store, status="retry_pending")

    def no_emitter_lock(self, emitter_id: str) -> str | None:
        raise AssertionError(f"emitter {emitter_id} was locked for a SIFEN query")

    monkeypatch.setattr(
        SqlAlchemyEmitterRepository, "get_status_for_update", no_emitter_lock
    )

    document, outcome = _query(
        session_factory, store, _Gateway(status="found"), reconcile=True
    )

    assert outcome.status == "found"
    assert document.internal_status == "approved"


def test_reconcile_converges_a_document_left_submitting_by_a_dead_worker(
    database_url: str,
    store: EncryptedCertificateStore,
) -> None:
    session_factory = _seed(database_url, store, status="submitting")

    document, _ = _query(
        session_factory, store, _Gateway(status="found"), reconcile=True
    )

    assert document.internal_status == "approved"
    with session_scope(session_factory) as session:
        job = SqlAlchemyJobRepository(session).get("job-1")
    assert job is not None and job.status == "succeeded"


def test_reconcile_keeps_a_result_recorded_while_sifen_answered(
    database_url: str,
    store: EncryptedCertificateStore,
) -> None:
    session_factory = _seed(database_url, store, status="retry_pending")

    def worker_records_rejection() -> None:
        with session_scope(session_factory) as session:
            documents = SqlAlchemyDocumentRepository(session)
            current = documents.get("document-1")
            assert current is not None
            documents.save(replace(current, internal_status="rejected"))

    document, _ = _query(
        session_factory,
        store,
        _Gateway(status="found", during_call=worker_records_rejection),
        reconcile=True,
    )

    assert document.internal_status == "rejected"
    assert document.last_query_response_raw == "<found/>"
    with session_scope(session_factory) as session:
        job = SqlAlchemyJobRepository(session).get("job-1")
    assert job is not None and job.status == "retry_scheduled"


@pytest.mark.requires_postgres
def test_emitter_row_is_free_while_sifen_is_queried(
    store: EncryptedCertificateStore,
    tmp_path: Path,
) -> None:
    if not os.getenv("KILA_SIFEN_TEST_DATABASE_URL"):
        pytest.skip("KILA_SIFEN_TEST_DATABASE_URL is required for row-lock tests.")
    with managed_test_database_url(tmp_path=tmp_path, name="query_free") as url:
        session_factory = _seed(url, store, status="retry_pending")

        def emitter_lock_is_free() -> None:
            with session_scope(session_factory) as session:
                session.execute(
                    select(EmitterModel.id)
                    .where(EmitterModel.id == "emitter-1")
                    .with_for_update(nowait=True)
                )

        _query(
            session_factory,
            store,
            _Gateway(status="found", during_call=emitter_lock_is_free),
            reconcile=True,
        )


class _Gateway:
    def __init__(
        self,
        *,
        status: str,
        during_call: Callable[[], None] | None = None,
    ) -> None:
        self.status = status
        self.during_call = during_call

    def query_document(self, **kwargs) -> DocumentQueryOutcome:
        del kwargs
        if self.during_call is not None:
            self.during_call()
        found = self.status == "found"
        return DocumentQueryOutcome(
            cdc=_CDC,
            request_xml="<query/>",
            response_raw="<found/>" if found else "<not-found/>",
            result_code="0422" if found else "0420",
            result_message="consulta ficticia",
            status=self.status,
            content_xml="<rDE/>" if found else None,
            processed_at=None,
        )


def _query(session_factory, store, gateway, *, reconcile: bool):
    with session_scope(session_factory) as session:
        service = QueryService(
            emitter_repository=SqlAlchemyEmitterRepository(session, store),
            certificate_repository=SqlAlchemyCertificateRepository(session),
            document_repository=SqlAlchemyDocumentRepository(session),
            job_repository=SqlAlchemyJobRepository(session),
            certificate_store=store,
            query_gateway=gateway,
        )
        return service.query_document(
            emitter_id="emitter-1",
            document_id="document-1",
            reconcile=reconcile,
        )


def _seed(database_url: str, store: EncryptedCertificateStore, *, status: str):
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    with session_scope(session_factory) as session:
        SqlAlchemyEmitterRepository(session, store).save(
            Emitter(
                id="emitter-1",
                external_id="erp-1",
                ruc="80024135",
                dv="5",
                legal_name="EMISOR FICTICIO SA",
                tax_environment="test",
                status="active",
                csc=None,
                csc_id=None,
                created_at=_now(),
                updated_at=_now(),
            )
        )
        SqlAlchemyCertificateRepository(session).save(
            Certificate(
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
        )
        SqlAlchemyDocumentRepository(session).save(
            Document(
                id="document-1",
                emitter_id="emitter-1",
                external_id=None,
                idempotency_key=None,
                document_type="factura",
                payload_snapshot={},
                generated_xml="<rDE/>",
                signed_xml="<rDE><Signature/></rDE>",
                sifen_request_xml="<rEnviDe/>",
                sifen_response_raw=None,
                last_query_request_xml=None,
                last_query_response_raw=None,
                last_query_at=None,
                cdc=_CDC,
                internal_status=status,
                sifen_status=status,
                sifen_result_code=None,
                sifen_result_message=None,
                created_at=_now(),
                updated_at=_now(),
            )
        )
        SqlAlchemyJobRepository(session).save(
            Job(
                id="job-1",
                emitter_id="emitter-1",
                related_entity_type="document",
                related_entity_id="document-1",
                job_type="document.emit",
                status="retry_scheduled",
                attempts=1,
                error_snapshot=None,
                scheduled_at=_now(),
                started_at=_now(),
                finished_at=None,
                worker_correlation_id=None,
                created_at=_now(),
                updated_at=_now(),
            )
        )
    return session_factory


def _now() -> datetime:
    return datetime.now(timezone.utc)
