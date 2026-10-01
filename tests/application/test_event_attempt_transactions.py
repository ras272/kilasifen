"""An event attempt commits its exact request before SIFEN and records after.

What to do after an uncertain event (resend or query first) is a pending
fiscal decision: these tests pin the current behaviour (the next attempt sends
the stored signed event again) and the engineering guarantees around it.
"""

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, update

import kilasifen.application.events.service as event_service_module
from kilasifen.application.events.service import EventService
from kilasifen.domain.common.errors import ServiceUnavailableError
from kilasifen.engine.sdk.errors import (
    SifenRequestNotSentError,
    SifenTimeoutError,
    SifenUnexpectedResponseError,
    SifenValidationError,
)
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
from kilasifen.infrastructure.db.repositories.events import SqlAlchemyEventRepository
from kilasifen.infrastructure.db.repositories.inutilized_number_ranges import (
    SqlAlchemyInutilizedNumberRangeRepository,
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
from kilasifen.infrastructure.jobs.workers import process_event_job
from kilasifen.infrastructure.sifen.event import (
    EventSubmissionOutcome,
    PreparedEventSubmission,
)
from kilasifen.testing.database import managed_test_database_url
from tests.api.test_events_api import RecordingEventQueue, _seed_event_context

_EVENT_XML = "<gGroupGesEve>evento firmado</gGroupGesEve>"
_APPROVED = EventSubmissionOutcome(
    response_raw="<rRetEnviEventoDe>aprobado</rRetEnviEventoDe>",
    status="approved",
    result_code="0600",
    result_message="Evento registrado correctamente",
    protocol="90001234",
)


class _WorkerKilled(BaseException):
    """Stands for SIGKILL/OOM: nothing in the worker may catch it."""


@dataclass
class _Gateway:
    """Event gateway double; every prepare builds a request with a new dId."""

    outcome: EventSubmissionOutcome = field(default_factory=lambda: _APPROVED)
    prepare_error: Exception | None = None
    submit_error: BaseException | None = None
    during_submit: Callable[[], None] | None = None
    prepared_requests: list[str] = field(default_factory=list)
    submitted_requests: list[str] = field(default_factory=list)

    def prepare_event(self, *, event, **kwargs) -> PreparedEventSubmission:
        del kwargs
        if self.prepare_error is not None:
            raise self.prepare_error
        request = f"<rEnviEventoDe><dId>{len(self.prepared_requests) + 1}</dId>"
        request += f"<dEvReg>{event.generated_xml}</dEvReg></rEnviEventoDe>"
        self.prepared_requests.append(request)
        return PreparedEventSubmission(
            signed_xml=event.generated_xml,
            request_xml=request,
        )

    def submit_prepared(self, *, request_xml: str, **kwargs) -> EventSubmissionOutcome:
        del kwargs
        self.submitted_requests.append(request_xml)
        if self.during_submit is not None:
            self.during_submit()
        if self.submit_error is not None:
            raise self.submit_error
        return self.outcome


@dataclass
class _Context:
    database_url: str
    encryption_key: str
    job_id: str
    event_id: str


@pytest.fixture
def context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Context]:
    monkeypatch.setattr(
        event_service_module,
        "build_signed_cancel_event_group_xml",
        lambda **_: _EVENT_XML,
    )
    with managed_test_database_url(tmp_path=tmp_path, name="event_txn") as url:
        encryption_key = Fernet.generate_key().decode()
        store = EncryptedCertificateStore(encryption_key)
        engine = build_engine(url)
        Base.metadata.create_all(engine)
        session_factory = build_session_factory(engine)
        _seed_event_context(session_factory=session_factory, certificate_store=store)
        with session_scope(session_factory) as session:
            event, job = EventService(
                event_repository=SqlAlchemyEventRepository(session),
                emitter_repository=SqlAlchemyEmitterRepository(session, store),
                document_repository=SqlAlchemyDocumentRepository(session),
                certificate_repository=SqlAlchemyCertificateRepository(session),
                job_repository=SqlAlchemyJobRepository(session),
                certificate_store=store,
                submission_gateway=_Gateway(),
                inutilized_range_repository=(
                    SqlAlchemyInutilizedNumberRangeRepository(session)
                ),
                queue=RecordingEventQueue(),
                database_url=url,
                encryption_key=encryption_key,
            ).cancel_document(
                emitter_id="emitter-1",
                document_id="doc-fe-recent",
                motivo="Cancelacion durable de prueba",
            )
        yield _Context(url, encryption_key, job.id, event.id)


def test_the_exact_request_is_committed_before_sifen_is_called(
    context: _Context,
) -> None:
    seen: dict = {}

    def read_committed_state() -> None:
        seen["event"], seen["job"] = _load(context)

    gateway = _Gateway(during_submit=read_committed_state)
    payload = _run(context, gateway)

    assert seen["event"].status == "submitting"
    assert seen["event"].signed_xml == _EVENT_XML
    assert seen["event"].sifen_request_xml == gateway.submitted_requests[0]
    assert seen["job"].status == "processing" and seen["job"].attempts == 1
    assert payload["event_status"] == "approved"
    event, _ = _load(context)
    assert event.sifen_request_xml == gateway.submitted_requests[0]
    assert event.sifen_response_raw == _APPROVED.response_raw


@pytest.mark.skipif(
    bool(os.getenv("KILA_SIFEN_TEST_DATABASE_URL")),
    reason="SQLite locks the whole database file",
)
def test_no_database_write_lock_is_held_while_sifen_answers(context: _Context) -> None:
    impatient = create_engine(context.database_url, connect_args={"timeout": 0.2})

    def write_from_another_connection() -> None:
        with impatient.begin() as connection:
            connection.execute(
                update(EmitterModel)
                .where(EmitterModel.id == "emitter-1")
                .values(legal_name="EMISOR RENOMBRADO SA")
            )

    try:
        _run(context, _Gateway(during_submit=write_from_another_connection))
    finally:
        impatient.dispose()


def test_a_request_that_never_left_is_recorded_and_sent_again(
    context: _Context,
) -> None:
    payload = _run(
        context,
        _Gateway(submit_error=SifenRequestNotSentError("La solicitud no llego")),
    )

    event, job = _load(context)
    assert payload["retryable"] is True
    assert event.status == "queued"
    assert job.error_snapshot["category"] == "transport_not_sent"
    assert _outbox_status(context) == "pending"

    retry = _Gateway()
    assert _run(context, retry)["event_status"] == "approved"
    assert len(retry.submitted_requests) == 1


@pytest.mark.parametrize(
    "failure",
    [
        SifenTimeoutError("timeout de lectura"),
        SifenUnexpectedResponseError(
            expected_root="rRetEnviEventoDe", actual_root="invalid_xml"
        ),
        ValueError("<rEve>dato del contribuyente</rEve>"),
    ],
)
def test_an_uncertain_event_is_recorded_and_the_retry_resends_it(
    context: _Context,
    failure: Exception,
) -> None:
    payload = _run(context, _Gateway(submit_error=failure))

    event, job = _load(context)
    assert payload["retryable"] is True
    assert event.status == "retry_pending"
    assert event.sifen_request_xml is not None
    assert job.error_snapshot["category"] == "transport"
    assert "contribuyente" not in job.error_snapshot["message"]

    # Pending fiscal decision: today the retry sends the stored event again.
    retry = _Gateway()
    assert _run(context, retry)["event_status"] == "approved"
    assert retry.submitted_requests


def test_a_crash_during_the_call_leaves_the_attempt_on_record(
    context: _Context,
) -> None:
    gateway = _Gateway(submit_error=_WorkerKilled())
    with pytest.raises(_WorkerKilled):
        _run(context, gateway)

    event, job = _load(context)
    assert event.status == "submitting"
    assert event.sifen_request_xml == gateway.submitted_requests[0]
    assert job.status == "processing" and job.attempts == 1


def test_an_approval_recorded_meanwhile_is_not_overwritten(
    context: _Context,
) -> None:
    def other_attempt_approves() -> None:
        with _session(context) as session:
            events = SqlAlchemyEventRepository(session)
            jobs = SqlAlchemyJobRepository(session)
            events.save(replace(events.get(context.event_id), status="approved"))
            jobs.save(replace(jobs.get(context.job_id), status="succeeded"))

    payload = _run(
        context,
        _Gateway(
            submit_error=SifenTimeoutError("timeout de lectura"),
            during_submit=other_attempt_approves,
        ),
    )

    event, job = _load(context)
    assert payload["event_status"] == "approved"
    assert payload["retryable"] is False
    assert event.status == "approved"
    assert job.status == "succeeded"


def test_a_busy_emitter_reschedules_the_event_job(
    context: _Context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SqlAlchemyEmitterRepository, "get_status_for_update", _busy_emitter
    )
    gateway = _Gateway()

    with pytest.raises(ServiceUnavailableError):
        _run(context, gateway)

    event, job = _load(context)
    assert gateway.submitted_requests == []
    assert event.status == "queued"
    assert job.status == "queued" and job.attempts == 0
    assert job.error_snapshot["category"] == "emitter_busy"
    assert _outbox_status(context) == "pending"


def test_an_operator_retry_of_a_failed_event_survives_a_busy_emitter(
    context: _Context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refused = _Gateway(prepare_error=SifenValidationError("firma invalida"))
    assert _run(context, refused)["event_status"] == "failed"
    _requeue(context)

    with monkeypatch.context() as busy:
        busy.setattr(
            SqlAlchemyEmitterRepository, "get_status_for_update", _busy_emitter
        )
        with pytest.raises(ServiceUnavailableError):
            _run(context, _Gateway())

    event, job = _load(context)
    assert event.status == "failed"
    assert job.status == "queued"
    assert _outbox_status(context) == "pending"

    gateway = _Gateway()
    payload = _run(context, gateway)

    assert len(gateway.submitted_requests) == 1
    assert payload["event_status"] == "approved"
    assert payload["job_status"] == "succeeded"


def _busy_emitter(self, emitter_id: str) -> str | None:
    del self, emitter_id
    raise ServiceUnavailableError("emitters.lock_timeout")


def _run(context: _Context, gateway: _Gateway) -> dict:
    return process_event_job(
        job_id=context.job_id,
        database_url=context.database_url,
        encryption_key=context.encryption_key,
        submission_gateway=gateway,
    )


def _session(context: _Context):
    return session_scope(build_session_factory(build_engine(context.database_url)))


def _load(context: _Context):
    with _session(context) as session:
        event = SqlAlchemyEventRepository(session).get(context.event_id)
        job = SqlAlchemyJobRepository(session).get(context.job_id)
    assert event is not None and job is not None
    return event, job


def _requeue(context: _Context) -> None:
    """What an operator retry does to the job (``AdminService.retry_job``)."""

    with _session(context) as session:
        jobs = SqlAlchemyJobRepository(session)
        job = jobs.get(context.job_id)
        jobs.save(
            replace(job, status="queued", finished_at=None, error_snapshot=None)
        )


def _outbox_status(context: _Context) -> str | None:
    with _session(context) as session:
        message = SqlAlchemyJobOutboxRepository(session).get_for_job(context.job_id)
    return message.status if message is not None else None
