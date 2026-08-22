from dataclasses import replace
from datetime import date

import pytest

from kilasifen.config import get_settings
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.repositories.documents import (
    SqlAlchemyDocumentRepository,
)
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from kilasifen.infrastructure.jobs.workers import process_document_job
from kilasifen.infrastructure.sandbox.transport import DeterministicSandboxTransport
from kilasifen.testing.database import managed_test_database_url
from tests.application.test_emission_flow import (
    _fernet_key,
    _seed_emission_context,
)

_SIGNED_XML = '<rDE><DE Id="0180012345"/><Signature/></rDE>'


def test_accepted_response_lost_reconciles_by_cdc_without_resubmission(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _sandbox_document(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        database_name="sandbox-accepted-response-lost",
        outcome="accepted_but_response_lost",
    ) as database_url:
        result = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            current_date=date(2024, 4, 24),
        )
        assert result["job_status"] == "retry_scheduled"

        first_document, _ = _load_context(database_url)
        assert first_document.internal_status == "retry_pending"
        assert first_document.cdc == "0180012345"
        immutable_request = first_document.sifen_request_xml

        monkeypatch.setattr(
            DeterministicSandboxTransport,
            "submit",
            _fail_if_resubmitted,
        )
        result = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            current_date=date(2024, 4, 24),
        )

        document, job = _load_context(database_url)
        assert result["document_status"] == "approved"
        assert result["job_status"] == "succeeded"
        assert document.cdc == "0180012345"
        assert document.sifen_request_xml == immutable_request
        assert document.last_query_response_raw is not None
        assert "<status>found</status>" in document.last_query_response_raw
        assert job.attempts == 2


def test_transport_timeout_queries_same_cdc_and_never_resubmits(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _sandbox_document(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        database_name="sandbox-transport-timeout",
        outcome="transport_timeout",
    ) as database_url:
        result = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            current_date=date(2024, 4, 24),
        )
        assert result["job_status"] == "retry_scheduled"

        first_document, _ = _load_context(database_url)
        assert first_document.cdc == "0180012345"
        immutable_request = first_document.sifen_request_xml

        monkeypatch.setattr(
            DeterministicSandboxTransport,
            "submit",
            _fail_if_resubmitted,
        )
        for _ in range(3):
            result = process_document_job(
                job_id="job-1",
                database_url=database_url,
                encryption_key=_fernet_key(),
                current_date=date(2024, 4, 24),
            )
            assert result["job_status"] == "retry_scheduled"
        result = process_document_job(
            job_id="job-1",
            database_url=database_url,
            encryption_key=_fernet_key(),
            current_date=date(2024, 4, 24),
        )

        document, job = _load_context(database_url)
        assert result["document_status"] == "reconciliation_required"
        assert result["job_status"] == "failed"
        assert document.internal_status == "reconciliation_required"
        assert document.cdc == "0180012345"
        assert document.sifen_request_xml == immutable_request
        assert document.last_query_response_raw is not None
        assert "<status>not_found</status>" in document.last_query_response_raw
        assert job.status == "failed"
        assert job.attempts == 5
        assert job.error_snapshot["category"] == "reconciliation_required"


class _sandbox_document:
    def __init__(
        self,
        *,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
        database_name: str,
        outcome: str,
    ) -> None:
        self.tmp_path = tmp_path
        self.monkeypatch = monkeypatch
        self.database_name = database_name
        self.outcome = outcome
        self.database_context = None

    def __enter__(self) -> str:
        self.monkeypatch.setenv("KILA_SIFEN_ENVIRONMENT", "test")
        get_settings.cache_clear()
        self.database_context = managed_test_database_url(
            tmp_path=self.tmp_path,
            name=self.database_name,
        )
        database_url = self.database_context.__enter__()
        store = EncryptedCertificateStore(_fernet_key())
        _seed_emission_context(database_url, store)

        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            repository = SqlAlchemyDocumentRepository(session)
            document = repository.get("document-1")
            assert document is not None
            repository.save(
                replace(
                    document,
                    payload_snapshot={
                        "generated_xml": '<rDE><DE Id="0180012345"/></rDE>',
                        "signed_xml": _SIGNED_XML,
                        "doc_id": "0180012345",
                        "sandbox": {"version": 1, "outcome": self.outcome},
                    },
                )
            )
        return database_url

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        get_settings.cache_clear()
        assert self.database_context is not None
        self.database_context.__exit__(exc_type, exc_value, traceback)


def _load_context(database_url: str):
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    with session_scope(session_factory) as session:
        document = SqlAlchemyDocumentRepository(session).get("document-1")
        job = SqlAlchemyJobRepository(session).get("job-1")
    assert document is not None and job is not None
    return document, job


def _fail_if_resubmitted(self, **kwargs):
    del self, kwargs
    raise AssertionError("ambiguous CDC must never be resubmitted")
