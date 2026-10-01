"""An event attempt commits its exact request before SIFEN and records after.

After an uncertain attempt, a cancellation is reconciled through its CDC
(siConsDE, rContDe/xContEv) before it is sent again, and a suspicious
rejection (4002/4003/4009/4010) is only believed once the CDC shows no
registered cancellation (DECISIONES F70; MT v150 §9.4.3, §11.6.1).
"""

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text, update

import kilasifen.application.events.service as event_service_module
from kilasifen.application.events.attempts import (
    EVENT_IN_FLIGHT_WINDOW,
    EventAttempt,
)
from kilasifen.application.events.service import EventService
from kilasifen.application.webhooks.service import WebhookService
from kilasifen.config import get_settings
from kilasifen.domain.common.errors import ServiceUnavailableError
from kilasifen.domain.webhooks.models import WebhookEndpoint
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
from kilasifen.infrastructure.db.repositories.webhooks import (
    SqlAlchemyWebhookRepository,
)
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
from kilasifen.infrastructure.sifen.query import (
    QUERY_ERROR,
    QUERY_FOUND,
    QUERY_NOT_FOUND_OR_NOT_APPROVED,
    DocumentQueryOutcome,
)
from kilasifen.infrastructure.sifen.responses import (
    DocumentContainer,
    RegisteredEvent,
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
class _Query:
    """siConsDE double for the cancelled document.

    ``readable=False`` stands for an ``xContenDE`` the platform could not
    parse (its form is NO DETERMINADO): 0422 without a container.
    """

    status: str = QUERY_FOUND
    cancellation_registered: bool = False
    readable: bool = True
    error: Exception | None = None
    calls: int = 0

    def query_document(self, *, cdc: str, **kwargs) -> DocumentQueryOutcome:
        del kwargs
        self.calls += 1
        if self.error is not None:
            raise self.error
        codes = {QUERY_FOUND: "0422", QUERY_NOT_FOUND_OR_NOT_APPROVED: "0420"}
        events = (
            (
                RegisteredEvent(
                    kind="cancelacion",
                    cdc=cdc,
                    protocol="7700112233",
                    state_text="Aprobado",
                ),
            )
            if self.cancellation_registered
            else ()
        )
        found = self.status == QUERY_FOUND
        return DocumentQueryOutcome(
            cdc=cdc,
            request_xml="<rEnviConsDeRequest/>",
            response_raw="<rEnviConsDeResponse/>",
            result_code=codes.get(self.status, "0421"),
            result_message="consulta",
            status=self.status,
            content_xml="<rContDe/>" if found else None,
            processed_at=None,
            container=DocumentContainer(
                document_xml="<rDE/>", protocol="1", events=events
            )
            if found and self.readable
            else None,
        )


def _rejection(code: str) -> EventSubmissionOutcome:
    return EventSubmissionOutcome(
        response_raw=f"<rRetEnviEventoDe>{code}</rRetEnviEventoDe>",
        status="rejected",
        result_code=code,
        result_message=f"rechazo {code}",
        protocol=None,
    )


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


@pytest.fixture
def cancellation_webhooks(
    context: _Context,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Publish fiscal event webhooks to one endpoint subscribed to all."""

    with _session(context) as session:
        SqlAlchemyWebhookRepository(session).save_endpoint(
            WebhookEndpoint(
                id="endpoint-1",
                emitter_id="emitter-1",
                url="https://erp.example.com/hooks/kila",
                secret_encrypted=EncryptedCertificateStore(
                    context.encryption_key
                ).encrypt_text("top-secret"),
                event_subscriptions=None,
                is_active=True,
                retry_policy=None,
                created_at=_now(),
                updated_at=_now(),
            )
        )
    monkeypatch.setenv("KILA_SIFEN_DOCUMENT_PUBLISH_WEBHOOKS", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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
def test_an_uncertain_cancellation_is_queried_before_it_is_sent_again(
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

    # SIFEN holds the DTE without a cancellation: the event travels again.
    query = _Query(status=QUERY_FOUND)
    retry = _Gateway()
    assert _run(context, retry, query=query)["event_status"] == "approved"
    assert query.calls == 1
    assert len(retry.submitted_requests) == 1


def test_a_cancellation_already_registered_is_not_sent_again(
    context: _Context,
) -> None:
    _run(context, _Gateway(submit_error=SifenTimeoutError("timeout de lectura")))

    retry = _Gateway()
    payload = _run(
        context, retry, query=_Query(status=QUERY_FOUND, cancellation_registered=True)
    )

    event, job = _load(context)
    assert retry.submitted_requests == []
    assert payload["event_status"] == "approved"
    assert event.sifen_result_code == "0422"
    assert job.status == "succeeded"
    with _session(context) as session:
        document = SqlAlchemyDocumentRepository(session).get("doc-fe-recent")
    assert document.internal_status == "cancelled"
    # The siConsDE that settled the cancellation is kept on the document.
    assert document.last_query_response_raw == "<rEnviConsDeResponse/>"


def test_an_answer_without_code_is_reconciled_before_a_resend(
    context: _Context,
) -> None:
    unclassified = EventSubmissionOutcome(
        response_raw="<rRetEnviEventoDe/>",
        status="submitted",
        result_code=None,
        result_message=None,
        protocol=None,
    )
    _run(context, _Gateway(outcome=unclassified))
    event, _ = _load(context)
    assert event.status == "submitted"

    retry = _Gateway()
    payload = _run(
        context, retry, query=_Query(status=QUERY_FOUND, cancellation_registered=True)
    )

    assert retry.submitted_requests == []
    assert payload["event_status"] == "approved"


def test_an_unanswerable_cdc_leaves_the_cancellation_to_an_operator(
    context: _Context,
) -> None:
    _run(context, _Gateway(submit_error=SifenTimeoutError("timeout de lectura")))

    retry = _Gateway()
    payload = _run(
        context, retry, query=_Query(status=QUERY_NOT_FOUND_OR_NOT_APPROVED)
    )

    event, job = _load(context)
    # Whether a cancelled DTE answers 0420 is NO DETERMINADO: nothing is sent.
    assert retry.submitted_requests == []
    assert payload["event_status"] == "reconciliation_required"
    assert event.status == "reconciliation_required"
    assert job.status == "failed"
    assert job.error_snapshot["category"] == "reconciliation_required"


@pytest.mark.parametrize(
    "query",
    [
        _Query(error=SifenTimeoutError("timeout de la consulta")),
        _Query(status=QUERY_ERROR),
    ],
)
def test_a_failed_cdc_query_sends_nothing_and_is_tried_again(
    context: _Context,
    query: _Query,
) -> None:
    _run(context, _Gateway(submit_error=SifenTimeoutError("timeout de lectura")))

    retry = _Gateway()
    payload = _run(context, retry, query=query)

    event, job = _load(context)
    assert retry.submitted_requests == []
    assert payload["retryable"] is True
    assert event.status == "retry_pending"
    assert job.error_snapshot["category"] == "reconciliation_unavailable"


@pytest.mark.parametrize("code", ["4002", "4003", "4009", "4010"])
def test_a_suspicious_rejection_hiding_a_registration_is_approved(
    context: _Context,
    code: str,
) -> None:
    payload = _run(
        context,
        _Gateway(outcome=_rejection(code)),
        query=_Query(status=QUERY_FOUND, cancellation_registered=True),
    )

    event, _ = _load(context)
    assert payload["event_status"] == "approved"
    assert event.sifen_response_raw == _rejection(code).response_raw
    with _session(context) as session:
        document = SqlAlchemyDocumentRepository(session).get("doc-fe-recent")
    assert document.internal_status == "cancelled"


@pytest.mark.parametrize("code", ["4002", "4009", "4010"])
def test_a_suspicious_rejection_is_believed_when_no_cancellation_is_registered(
    context: _Context,
    code: str,
) -> None:
    query = _Query(status=QUERY_FOUND)
    payload = _run(context, _Gateway(outcome=_rejection(code)), query=query)

    event, job = _load(context)
    assert query.calls == 1
    assert payload["event_status"] == "rejected"
    assert event.sifen_result_code == code
    assert job.error_snapshot["category"] == "sifen_rejection"


def test_a_duplicate_answer_is_never_read_as_a_rejection(context: _Context) -> None:
    """4003 (GEC002b, MT v150 §11.6.1 p. 134): SIFEN says it is registered.

    siConsDE finds the DTE but ``xContEv`` shows no cancellation: the two
    answers disagree, so the event is left for an operator and the document
    keeps its state instead of a false ``rejected`` (DECISIONES F00, F70).
    """

    query = _Query(status=QUERY_FOUND)
    payload = _run(context, _Gateway(outcome=_rejection("4003")), query=query)

    event, job = _load(context)
    assert query.calls == 1
    assert payload["event_status"] == "reconciliation_required"
    assert event.status == "reconciliation_required"
    assert event.sifen_result_code == "4003"
    assert event.sifen_response_raw == _rejection("4003").response_raw
    assert job.status == "failed"
    assert job.error_snapshot["category"] == "reconciliation_required"
    with _session(context) as session:
        document = SqlAlchemyDocumentRepository(session).get("doc-fe-recent")
    assert document.internal_status == "approved"


@pytest.mark.parametrize("code", ["4002", "4003", "4009", "4010"])
def test_a_suspicious_rejection_with_an_unreadable_container_is_not_believed(
    context: _Context,
    code: str,
) -> None:
    """0422 whose ``xContenDE`` cannot be read (form NO DETERMINADO)."""

    query = _Query(status=QUERY_FOUND, readable=False)
    payload = _run(context, _Gateway(outcome=_rejection(code)), query=query)

    event, job = _load(context)
    assert query.calls == 1
    assert payload["event_status"] == "reconciliation_required"
    assert event.sifen_result_code == code
    assert job.error_snapshot["category"] == "reconciliation_required"


def test_an_unreadable_container_after_an_uncertain_attempt_never_rejects(
    context: _Context,
) -> None:
    """The reviewer's probe: timeout, 0422 unreadable, resend, then 4003."""

    _run(context, _Gateway(submit_error=SifenTimeoutError("timeout de lectura")))

    # The stored event travels again; its 4003 is queried and not believed.
    query = _Query(status=QUERY_FOUND, readable=False)
    retry = _Gateway(outcome=_rejection("4003"))
    payload = _run(context, retry, query=query)

    event, job = _load(context)
    assert len(retry.submitted_requests) == 1
    assert query.calls == 2
    assert payload["event_status"] == "reconciliation_required"
    assert event.sifen_result_code == "4003"
    assert job.error_snapshot["category"] == "reconciliation_required"


def test_an_unreadable_container_lets_the_stored_event_settle_itself(
    context: _Context,
) -> None:
    """Without a readable ``xContEv`` the resend's own answer decides: 0600."""

    _run(context, _Gateway(submit_error=SifenTimeoutError("timeout de lectura")))

    retry = _Gateway()
    payload = _run(
        context, retry, query=_Query(status=QUERY_FOUND, readable=False)
    )

    assert len(retry.submitted_requests) == 1
    assert payload["event_status"] == "approved"


def test_an_ordinary_rejection_needs_no_query(context: _Context) -> None:
    query = _Query()
    payload = _run(context, _Gateway(outcome=_rejection("4006")), query=query)

    assert payload["event_status"] == "rejected"
    assert query.calls == 0


def test_an_uncertain_event_that_exhausts_its_attempts_needs_reconciliation(
    context: _Context,
) -> None:
    _run(context, _Gateway(submit_error=SifenTimeoutError("timeout de lectura")))
    _set_event_attempts(context, 4)

    payload = _run(
        context,
        _Gateway(),
        query=_Query(error=SifenTimeoutError("timeout de la consulta")),
    )

    event, job = _load(context)
    assert payload["event_status"] == "reconciliation_required"
    assert job.status == "failed"
    assert job.error_snapshot["category"] == "reconciliation_required"

    # An operator retry reconciles again before anything is sent.
    _requeue(context)
    retry = _Gateway()
    payload = _run(
        context, retry, query=_Query(status=QUERY_FOUND, cancellation_registered=True)
    )
    assert retry.submitted_requests == []
    assert payload["event_status"] == "approved"


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


def test_an_operator_retry_waits_while_the_first_request_may_be_at_sifen(
    context: _Context,
) -> None:
    with pytest.raises(_WorkerKilled):
        _run(context, _Gateway(submit_error=_WorkerKilled()))
    stored, _ = _load(context)
    _requeue(context)

    retry = _Gateway()
    payload = _run(context, retry)

    event, job = _load(context)
    assert retry.prepared_requests == [] and retry.submitted_requests == []
    assert payload["event_status"] == "submitting"
    assert event.sifen_request_xml == stored.sifen_request_xml
    assert job.status == "queued" and job.attempts == 1
    assert job.error_snapshot["category"] == "attempt_in_flight"
    assert _utc(job.scheduled_at) == _utc(stored.updated_at) + EVENT_IN_FLIGHT_WINDOW
    assert _outbox_status(context) == "pending"


def test_a_duplicate_dispatch_leaves_the_running_attempt_alone(
    context: _Context,
) -> None:
    duplicate = _Gateway()
    seen: dict = {}

    def same_job_runs_again() -> None:
        seen["payload"] = _run(context, duplicate)

    first = _Gateway(during_submit=same_job_runs_again)
    payload = _run(context, first)

    assert duplicate.prepared_requests == [] and duplicate.submitted_requests == []
    assert seen["payload"]["job_status"] == "processing"
    assert len(first.submitted_requests) == 1
    assert payload["event_status"] == "approved"
    _, job = _load(context)
    assert job.status == "succeeded" and job.attempts == 1


def test_a_retry_once_the_window_closed_sends_the_event_again(
    context: _Context,
) -> None:
    with pytest.raises(_WorkerKilled):
        _run(context, _Gateway(submit_error=_WorkerKilled()))
    _age_stored_request(context, EVENT_IN_FLIGHT_WINDOW + timedelta(seconds=1))
    _requeue(context)

    # The worker died: the CDC is queried first; no cancellation registered.
    retry = _Gateway()
    payload = _run(context, retry, query=_Query(status=QUERY_FOUND))

    assert len(retry.submitted_requests) == 1
    assert payload["event_status"] == "approved"


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


def test_the_outcome_is_recorded_under_the_shared_lock_order(
    context: _Context,
    cancellation_webhooks: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locks = _record_row_locks(monkeypatch)

    payload = _run(context, _Gateway(during_submit=lambda: locks.append("sifen")))

    assert payload["event_status"] == "approved"
    # The approved cancellation publishes a webhook, which locks the emitter
    # again: the recording transaction must already hold it.
    assert locks == [
        "emitter",
        "event",
        "job",
        "sifen",
        "emitter",
        "event",
        "job",
        "emitter",
    ]


def test_a_failed_webhook_publication_does_not_discard_the_outcome(
    context: _Context,
    cancellation_webhooks: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(WebhookService, "publish_event", _publish_then_fail)

    payload = _run(context, _Gateway())

    event, job = _load(context)
    assert payload["event_status"] == "approved"
    assert event.status == "approved"
    assert job.status == "succeeded"
    with _session(context) as session:
        document = SqlAlchemyDocumentRepository(session).get("doc-fe-recent")
        deliveries = SqlAlchemyWebhookRepository(session).list_recent_deliveries(
            limit=10
        )
    assert document.internal_status == "cancelled"
    assert deliveries == []


def _busy_emitter(self, emitter_id: str) -> str | None:
    del self, emitter_id
    raise ServiceUnavailableError("emitters.lock_timeout")


_ORIGINAL_PUBLISH_EVENT = WebhookService.publish_event


def _publish_then_fail(self, **kwargs):
    """Write the deliveries, then hit a database error (aborts on PostgreSQL)."""

    _ORIGINAL_PUBLISH_EVENT(self, **kwargs)
    self.job_repository.session.execute(text("SELECT * FROM kila_missing_table"))


def _record_row_locks(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    locks: list[str] = []
    for owner, method, label in (
        (SqlAlchemyEmitterRepository, "get_status_for_update", "emitter"),
        (SqlAlchemyEmitterRepository, "lock_row", "emitter"),
        (SqlAlchemyEventRepository, "get_for_update", "event"),
        (SqlAlchemyJobRepository, "get_for_update", "job"),
    ):
        original = getattr(owner, method)

        def spy(self, row_id, *, _original=original, _label=label):
            locks.append(_label)
            return _original(self, row_id)

        monkeypatch.setattr(owner, method, spy)
    return locks


def _run(context: _Context, gateway: _Gateway, *, query: _Query | None = None) -> dict:
    return process_event_job(
        job_id=context.job_id,
        database_url=context.database_url,
        encryption_key=context.encryption_key,
        submission_gateway=gateway,
        query_gateway=query or _Query(error=AssertionError("unexpected query")),
    )


def _set_event_attempts(context: _Context, attempts: int) -> None:
    with _session(context) as session:
        jobs = SqlAlchemyJobRepository(session)
        jobs.save(replace(jobs.get(context.job_id), attempts=attempts))


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


def _age_stored_request(context: _Context, age: timedelta) -> None:
    with _session(context) as session:
        events = SqlAlchemyEventRepository(session)
        event = events.get(context.event_id)
        events.save(replace(event, updated_at=_now() - age))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_an_attempt_repr_never_shows_the_certificate() -> None:
    attempt = EventAttempt(
        job_id="job-1",
        event_id="event-1",
        attempt_number=1,
        request_xml="<rEnviEventoDe/>",
        emitter=None,
        certificate_bytes=b"pkcs12-bytes",
        certificate_password="pfx-password",
    )

    assert "pkcs12-bytes" not in repr(attempt)
    assert "pfx-password" not in repr(attempt)
