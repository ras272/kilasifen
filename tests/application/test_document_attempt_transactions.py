"""A document attempt commits its submission before SIFEN and records after it.

These tests run against the database the suite is configured with (SQLite by
default) and simulate what happens around the SIFEN call: a crash, an
unreadable answer, a request that never left, another writer recording an
outcome meanwhile.
"""

import os
from dataclasses import replace
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, select, update
from xsdata.exceptions import ParserError

from kilasifen.domain.common.errors import ServiceUnavailableError
from kilasifen.engine.sdk.errors import (
    SifenRequestNotSentError,
    SifenTimeoutError,
    SifenTransportClosedError,
    SifenUnexpectedResponseError,
    SifenValidationError,
)
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.models import (
    DocumentModel,
    EmitterModel,
    JobModel,
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
from kilasifen.infrastructure.db.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from kilasifen.infrastructure.jobs.workers import process_document_job
from kilasifen.infrastructure.sifen.engine import (
    KilaSifenEmissionEngine,
    SubmissionOutcome,
)
from kilasifen.testing.database import managed_test_database_url
from tests.application.test_emission_flow import (
    _PREPARED,
    FakeEmissionEngine,
    FakeQueryGateway,
    _fernet_key,
    _seed_emission_context,
)

_APPROVED = SubmissionOutcome(
    response_raw="<rRetEnviDe>aprobado</rRetEnviDe>",
    sifen_status="approved",
    result_code="0260",
    result_message="Autorizacion satisfactoria",
)
_USES_POSTGRES = bool(os.getenv("KILA_SIFEN_TEST_DATABASE_URL"))


class _WorkerKilled(BaseException):
    """Stands for SIGKILL/OOM: nothing in the worker may catch it."""


@pytest.fixture
def database_url(tmp_path):
    with managed_test_database_url(tmp_path=tmp_path, name="attempt_txn") as url:
        _seed_emission_context(url, EncryptedCertificateStore(_fernet_key()))
        yield url


def test_submission_is_committed_before_sifen_is_called(database_url: str) -> None:
    seen: dict = {}

    def read_committed_state() -> None:
        seen["document"], seen["job"] = _load(database_url)

    engine = FakeEmissionEngine(outcome=_APPROVED, during_submit=read_committed_state)
    payload = _run(database_url, engine)

    document, job = seen["document"], seen["job"]
    assert document.internal_status == "submitting"
    assert document.generated_xml == _PREPARED.generated_xml
    assert document.signed_xml == _PREPARED.signed_xml
    assert document.sifen_request_xml == _PREPARED.request_xml
    assert document.cdc == _PREPARED.cdc
    assert job.status == "processing" and job.attempts == 1
    assert engine.submitted_requests == [_PREPARED.request_xml]
    assert payload["document_status"] == "approved"


@pytest.mark.skipif(_USES_POSTGRES, reason="SQLite locks the whole database file")
def test_no_database_write_lock_is_held_while_sifen_answers(database_url: str) -> None:
    impatient = create_engine(database_url, connect_args={"timeout": 0.2})

    def write_from_another_connection() -> None:
        with impatient.begin() as connection:
            connection.execute(
                update(EmitterModel)
                .where(EmitterModel.id == "emitter-1")
                .values(legal_name="EMISOR RENOMBRADO SA")
            )

    try:
        _run(
            database_url,
            FakeEmissionEngine(
                outcome=_APPROVED,
                during_submit=write_from_another_connection,
            ),
        )
    finally:
        impatient.dispose()


@pytest.mark.requires_postgres
@pytest.mark.skipif(not _USES_POSTGRES, reason="needs KILA_SIFEN_TEST_DATABASE_URL")
def test_no_row_lock_is_held_while_sifen_answers(database_url: str) -> None:
    session_factory = build_session_factory(build_engine(database_url))

    def lock_rows_without_waiting() -> None:
        with session_scope(session_factory) as session:
            for model, row_id in (
                (EmitterModel, "emitter-1"),
                (DocumentModel, "document-1"),
                (JobModel, "job-1"),
            ):
                session.execute(
                    select(model.id)
                    .where(model.id == row_id)
                    .with_for_update(nowait=True)
                )

    _run(
        database_url,
        FakeEmissionEngine(outcome=_APPROVED, during_submit=lock_rows_without_waiting),
    )


def test_a_crash_during_the_call_is_reconciled_by_cdc(database_url: str) -> None:
    with pytest.raises(_WorkerKilled):
        _run(database_url, FakeEmissionEngine(submit_error=_WorkerKilled()))

    document, job = _load(database_url)
    assert document.internal_status == "submitting"
    assert document.sifen_request_xml == _PREPARED.request_xml
    assert document.cdc == _PREPARED.cdc
    assert job.status == "processing" and job.attempts == 1

    _requeue(database_url)
    never_resubmitted = FakeEmissionEngine()
    payload = _run(
        database_url,
        never_resubmitted,
        query_gateway=FakeQueryGateway(status="found"),
    )

    document, job = _load(database_url)
    assert never_resubmitted.calls == []
    assert payload["document_status"] == "approved"
    assert document.sifen_request_xml == _PREPARED.request_xml
    assert job.status == "succeeded" and job.attempts == 2


def test_a_crash_followed_by_an_unanswered_query_keeps_reconciling(
    database_url: str,
) -> None:
    with pytest.raises(_WorkerKilled):
        _run(database_url, FakeEmissionEngine(submit_error=_WorkerKilled()))
    _requeue(database_url)

    never_resubmitted = FakeEmissionEngine()
    payload = _run(
        database_url,
        never_resubmitted,
        query_gateway=FakeQueryGateway(status="not_found"),
    )

    assert never_resubmitted.calls == []
    assert payload["document_status"] == "retry_pending"
    assert payload["job_status"] == "retry_scheduled"


@pytest.mark.parametrize(
    "never_left",
    [
        SifenRequestNotSentError("La solicitud no llego al SIFEN"),
        SifenTransportClosedError("transporte cerrado"),
    ],
)
def test_a_request_that_never_left_is_sent_again_unchanged(
    database_url: str,
    never_left: Exception,
) -> None:
    payload = _run(database_url, FakeEmissionEngine(submit_error=never_left))

    document, job = _load(database_url)
    assert payload["job_status"] == "retry_scheduled"
    assert document.internal_status == "queued"
    assert document.sifen_request_xml == _PREPARED.request_xml
    assert job.error_snapshot == {
        "category": "transport_not_sent",
        "message": str(never_left),
    }
    assert _outbox_status(database_url) == "pending"

    resend = FakeEmissionEngine(outcome=_APPROVED)
    payload = _run(database_url, resend)

    assert resend.calls == ["submit"]
    assert resend.submitted_requests == [_PREPARED.request_xml]
    assert payload["document_status"] == "approved"


@pytest.mark.parametrize(
    "failure",
    [
        SifenTimeoutError("timeout de lectura"),
        SifenUnexpectedResponseError(expected_root="rRetEnviDe", actual_root="Fault"),
        ParserError("Unknown property {ns}rRetEnviDe"),
        ValueError("<rDE>dato del contribuyente</rDE>"),
        RuntimeError("bug after the request left"),
    ],
)
def test_any_other_failure_leaves_the_outcome_unknown(
    database_url: str,
    failure: Exception,
) -> None:
    payload = _run(database_url, FakeEmissionEngine(submit_error=failure))

    document, job = _load(database_url)
    assert payload["job_status"] == "retry_scheduled"
    assert document.internal_status == "retry_pending"
    assert document.sifen_request_xml == _PREPARED.request_xml
    assert job.error_snapshot["category"] == "transport"
    assert "contribuyente" not in job.error_snapshot["message"]
    assert _outbox_status(database_url) == "pending"

    never_resubmitted = FakeEmissionEngine()
    _run(
        database_url,
        never_resubmitted,
        query_gateway=FakeQueryGateway(status="not_found"),
    )
    assert never_resubmitted.calls == []


def test_an_unreachable_sifen_on_the_last_attempt_keeps_the_document_queued(
    database_url: str,
) -> None:
    not_sent = SifenRequestNotSentError("La solicitud no llego al SIFEN")
    _run(database_url, FakeEmissionEngine(submit_error=not_sent))
    _set_attempts(database_url, 4)

    payload = _run(database_url, FakeEmissionEngine(submit_error=not_sent))

    document, job = _load(database_url)
    assert payload["job_status"] == "failed"
    assert document.internal_status == "queued"
    assert document.sifen_request_xml == _PREPARED.request_xml
    assert job.error_snapshot["category"] == "retry_exhausted"
    assert job.finished_at is not None

    _requeue(database_url)
    resend = FakeEmissionEngine(outcome=_APPROVED)
    payload = _run(database_url, resend)
    assert resend.calls == ["submit"]
    assert payload["document_status"] == "approved"


def test_an_unknown_outcome_on_the_last_attempt_requires_reconciliation(
    database_url: str,
) -> None:
    not_sent = SifenRequestNotSentError("La solicitud no llego al SIFEN")
    _run(database_url, FakeEmissionEngine(submit_error=not_sent))
    _set_attempts(database_url, 4)

    payload = _run(
        database_url,
        FakeEmissionEngine(submit_error=SifenTimeoutError("timeout de lectura")),
    )

    document, job = _load(database_url)
    assert payload["document_status"] == "reconciliation_required"
    assert document.internal_status == "reconciliation_required"
    assert job.status == "failed"
    assert job.error_snapshot["category"] == "reconciliation_required"


def test_an_outcome_recorded_meanwhile_is_not_overwritten(database_url: str) -> None:
    def operator_reconciles() -> None:
        with _session(database_url) as session:
            documents = SqlAlchemyDocumentRepository(session)
            jobs = SqlAlchemyJobRepository(session)
            document = documents.get("document-1")
            job = jobs.get("job-1")
            documents.save(replace(document, internal_status="approved"))
            jobs.save(replace(job, status="succeeded", finished_at=_now()))

    payload = _run(
        database_url,
        FakeEmissionEngine(
            submit_error=SifenTimeoutError("timeout de lectura"),
            during_submit=operator_reconciles,
        ),
    )

    document, job = _load(database_url)
    assert payload["document_status"] == "approved"
    assert document.internal_status == "approved"
    assert job.status == "succeeded"
    assert _outbox_status(database_url) is None


def test_an_intermediate_outcome_of_a_superseded_attempt_is_dropped(
    database_url: str,
) -> None:
    payload = _run(
        database_url,
        FakeEmissionEngine(
            submit_error=SifenRequestNotSentError("La solicitud no llego al SIFEN"),
            during_submit=lambda: _set_attempts(database_url, 2),
        ),
    )

    document, job = _load(database_url)
    assert payload["document_status"] == "submitting"
    assert document.internal_status == "submitting"
    assert job.attempts == 2
    assert _outbox_status(database_url) is None


def test_a_final_answer_of_a_superseded_attempt_is_still_recorded(
    database_url: str,
) -> None:
    payload = _run(
        database_url,
        FakeEmissionEngine(
            outcome=_APPROVED,
            during_submit=lambda: _set_attempts(database_url, 2),
        ),
    )

    document, job = _load(database_url)
    assert payload["document_status"] == "approved"
    assert document.sifen_response_raw == _APPROVED.response_raw
    assert job.status == "succeeded"


def test_the_persisted_request_is_exactly_the_one_sent(database_url: str) -> None:
    signed_xml = (
        '<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd">'
        f'<DE Id="{_PREPARED.cdc}"/><Signature/></rDE>'
    )
    mapper = Mock()
    mapper.map_document.return_value = SimpleNamespace(
        generated_xml=signed_xml,
        signed_xml=signed_xml,
        doc_id=_PREPARED.cdc,
    )
    sent: list[str] = []

    class RecordingTransport:
        def submit(self, *, request_xml: str, **kwargs) -> SubmissionOutcome:
            del kwargs
            sent.append(request_xml)
            return _APPROVED

    _run(
        database_url,
        KilaSifenEmissionEngine(mapper=mapper, transport=RecordingTransport()),
    )

    document, _ = _load(database_url)
    assert sent == [document.sifen_request_xml]
    assert "<dId>1</dId>" not in sent[0]
    assert f'<DE Id="{_PREPARED.cdc}"/><Signature/></rDE></xDE>' in sent[0]


def test_a_busy_emitter_reschedules_the_job_without_spending_an_attempt(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SqlAlchemyEmitterRepository, "get_status_for_update", _busy_emitter
    )
    engine = FakeEmissionEngine()
    before = _now()

    with pytest.raises(ServiceUnavailableError):
        _run(database_url, engine)

    document, job = _load(database_url)
    assert engine.calls == []
    assert document.internal_status == "queued"
    assert job.status == "queued" and job.attempts == 0
    assert job.scheduled_at.replace(tzinfo=timezone.utc) > before
    assert job.error_snapshot == {
        "category": "emitter_busy",
        "message": "emitters.lock_timeout",
    }
    assert _outbox_status(database_url) == "pending"


def test_an_operator_retry_of_a_failed_document_survives_a_busy_emitter(
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refused = FakeEmissionEngine(prepare_error=SifenValidationError("timbrado"))
    assert _run(database_url, refused)["document_status"] == "failed"
    _requeue(database_url)

    with monkeypatch.context() as busy:
        busy.setattr(
            SqlAlchemyEmitterRepository, "get_status_for_update", _busy_emitter
        )
        with pytest.raises(ServiceUnavailableError):
            _run(database_url, FakeEmissionEngine())

    document, job = _load(database_url)
    assert document.internal_status == "failed"
    assert job.status == "queued"
    assert _outbox_status(database_url) == "pending"

    engine = FakeEmissionEngine(outcome=_APPROVED)
    payload = _run(database_url, engine)

    assert engine.calls == ["prepare", "submit"]
    assert payload["document_status"] == "approved"
    assert payload["job_status"] == "succeeded"


def _busy_emitter(self, emitter_id: str) -> str | None:
    del self, emitter_id
    raise ServiceUnavailableError("emitters.lock_timeout")


def _run(database_url: str, engine, *, query_gateway=None) -> dict[str, str]:
    return process_document_job(
        job_id="job-1",
        database_url=database_url,
        encryption_key=_fernet_key(),
        emission_engine=engine,
        query_gateway=query_gateway or FakeQueryGateway(status="not_found"),
        current_date=date(2024, 4, 24),
    )


def _session(database_url: str):
    return session_scope(build_session_factory(build_engine(database_url)))


def _load(database_url: str):
    with _session(database_url) as session:
        document = SqlAlchemyDocumentRepository(session).get("document-1")
        job = SqlAlchemyJobRepository(session).get("job-1")
    assert document is not None and job is not None
    return document, job


def _requeue(database_url: str) -> None:
    with _session(database_url) as session:
        jobs = SqlAlchemyJobRepository(session)
        jobs.save(replace(jobs.get("job-1"), status="queued", finished_at=None))


def _set_attempts(database_url: str, attempts: int) -> None:
    with _session(database_url) as session:
        jobs = SqlAlchemyJobRepository(session)
        jobs.save(replace(jobs.get("job-1"), attempts=attempts))


def _outbox_status(database_url: str) -> str | None:
    with _session(database_url) as session:
        message = SqlAlchemyJobOutboxRepository(session).get_for_job("job-1")
    return message.status if message is not None else None


def _now() -> datetime:
    return datetime.now(timezone.utc)
