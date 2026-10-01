"""Worker entrypoints for background jobs."""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from typing import TypeVar

from rq import get_current_job
from sqlalchemy.orm import Session

from kilasifen.application.emitters.guards import require_active_emitter
from kilasifen.application.events.attempts import (
    DeferredEventJob,
    FinishedEventJob,
    send_event_attempt,
)
from kilasifen.application.events.service import EventService
from kilasifen.application.jobs.service import JobService
from kilasifen.application.sandbox.service import SandboxOutcomePolicy
from kilasifen.application.sifen_submissions import (
    describe_submission_failure,
    request_never_left,
)
from kilasifen.application.webhooks.service import WebhookService
from kilasifen.config import Settings, get_settings
from kilasifen.domain.common.errors import NotFoundError, ServiceUnavailableError
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.jobs.models import Job
from kilasifen.domain.stampings.models import Stamping
from kilasifen.engine.sdk.errors import (
    SifenError,
    SifenRejectionError,
    SifenValidationError,
)
from kilasifen.engine.sdk.signer import clear_pkcs12_signer_cache
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
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
from kilasifen.infrastructure.jobs.document_attempts import (
    AttemptAction,
    AttemptResult,
    OutcomeUnknown,
    PreparationRefused,
    Reconciled,
    ReconciliationRefused,
    ReconciliationUnavailable,
    RecordedAttempt,
    RequestNotSent,
    SifenAnswered,
    SifenRejected,
    conclude_attempt,
    conclude_claimed_attempt,
    is_finished,
    mark_submitting,
    select_action,
    start_attempt,
)
from kilasifen.infrastructure.jobs.outbox import SqlAlchemyJobOutboxQueue
from kilasifen.infrastructure.sandbox.query import DeterministicSandboxQueryGateway
from kilasifen.infrastructure.sandbox.transport import DeterministicSandboxTransport
from kilasifen.infrastructure.sifen.de_facts import paraguay_today, read_de_facts
from kilasifen.infrastructure.sifen.engine import (
    DocumentEmissionEngine,
    KilaSifenEmissionEngine,
)
from kilasifen.infrastructure.sifen.event import (
    EventSubmissionGateway,
    KilaSifenEventGateway,
)
from kilasifen.infrastructure.sifen.mapper import resolve_emission_date
from kilasifen.infrastructure.sifen.query import (
    KilaSifenQueryGateway,
    SifenQueryGateway,
)
from kilasifen.infrastructure.webhooks.deliverer import WebhookDeliverer
from kilasifen.infrastructure.webhooks.publisher import SavepointWebhookPublisher
from kilasifen.infrastructure.webhooks.security import WebhookUrlPolicy
from kilasifen.logging import (
    get_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from kilasifen.observability import ensure_worker_observability

logger = logging.getLogger(__name__)

_Row = TypeVar("_Row")

_EVENT_RETRY_DELAYS = (30, 120, 600, 1800)
#: Wait before trying again a job whose emitter row stayed locked.
_EMITTER_BUSY_RETRY_SECONDS = 30
#: Job states that wait for a worker; the outbox dispatches only these.
_WAITING_JOB_STATUSES = frozenset({"queued", "retry_scheduled"})


def process_document_job(
    *,
    job_id: str,
    database_url: str | None = None,
    encryption_key: str | None = None,
    emission_engine: DocumentEmissionEngine | None = None,
    query_gateway: SifenQueryGateway | None = None,
    current_date: date | None = None,
    webhook_queue=None,
) -> dict[str, str]:
    """Run one attempt of a document-emission job.

    The attempt commits the exact submission before calling SIFEN and records
    the outcome in a second transaction; no transaction or row lock is held
    while SIFEN answers (see ``document_attempts``).
    """

    settings = get_settings()
    database_url, encryption_key = _worker_runtime_secrets(
        database_url=database_url,
        encryption_key=encryption_key,
    )
    ensure_worker_observability()
    correlation_token, worker_correlation_id = _bind_worker_correlation_id()
    session_factory = build_session_factory(build_engine(database_url))
    certificate_store = EncryptedCertificateStore(encryption_key)

    def publish_status(document: Document, session: Session) -> None:
        _publish_document_status_webhooks(
            document=document,
            session=session,
            database_url=database_url,
            encryption_key=encryption_key,
            webhook_queue=webhook_queue,
        )

    try:
        with (
            _retry_later_if_emitter_busy(session_factory, job_id),
            session_scope(session_factory) as session,
        ):
            claim = _claim_document_attempt(
                session,
                job_id=job_id,
                runtime=_DocumentRuntime(
                    settings=settings,
                    certificate_store=certificate_store,
                    emission_engine=emission_engine,
                    query_gateway=query_gateway,
                    current_date=current_date or paraguay_today(),
                    worker_correlation_id=worker_correlation_id,
                ),
                publish_status=publish_status,
            )
        if isinstance(claim, _DocumentJobFinished):
            return claim.payload

        # The submission is committed: nothing below holds a transaction or a
        # row lock until SIFEN has answered (or failed to).
        result = _run_document_sifen_step(claim)

        with session_scope(session_factory) as session:
            return _record_document_attempt(
                session,
                claim=claim,
                result=result,
                publish_status=publish_status,
            )
    finally:
        _drop_cached_signing_keys()
        if correlation_token is not None:
            reset_correlation_id(correlation_token)


_StatusPublisher = Callable[[Document, Session], None]


@dataclass(frozen=True, slots=True)
class _DocumentRuntime:
    """Collaborators and settings shared by the steps of one document attempt.

    ``current_date`` (Paraguay) picks the timbrado only when the document
    does not say its emission date yet.
    """

    settings: Settings
    certificate_store: EncryptedCertificateStore
    emission_engine: DocumentEmissionEngine | None
    query_gateway: SifenQueryGateway | None
    current_date: date
    worker_correlation_id: str | None


@dataclass(frozen=True, slots=True)
class _DocumentJobFinished:
    """The attempt ended inside its first transaction; nothing goes to SIFEN."""

    payload: dict[str, str]


@dataclass(frozen=True, slots=True)
class _ClaimedDocumentAttempt:
    """What the first transaction committed for the SIFEN step."""

    job_id: str
    document_id: str
    attempt_number: int
    action: AttemptAction
    cdc: str | None
    request_xml: str | None
    emitter: Emitter
    # Kept out of repr so a log line or error report never carries them.
    certificate_bytes: bytes = field(repr=False)
    certificate_password: str = field(repr=False)
    emission_engine: DocumentEmissionEngine
    query_gateway: SifenQueryGateway


def _claim_document_attempt(
    session: Session,
    *,
    job_id: str,
    runtime: _DocumentRuntime,
    publish_status: _StatusPublisher,
) -> _ClaimedDocumentAttempt | _DocumentJobFinished:
    """First transaction: claim the job and make the submission durable."""

    job_repository = SqlAlchemyJobRepository(session)
    document_repository = SqlAlchemyDocumentRepository(session)
    emitter_repository = SqlAlchemyEmitterRepository(
        session, runtime.certificate_store
    )
    job, document = JobService(job_repository).get_document_job_context(
        job_id=job_id,
        document_repository=document_repository,
    )
    if is_finished(document, job):
        return _DocumentJobFinished(_document_job_payload(job, document))

    # Lock order shared by every writer: emitter, then document, then job.
    require_active_emitter(emitter_repository, document.emitter_id)
    document = _require_row(document_repository.get_for_update(document.id))
    job = _require_row(job_repository.get_for_update(job.id))
    if is_finished(document, job):
        return _DocumentJobFinished(_document_job_payload(job, document))

    emitter = emitter_repository.get(document.emitter_id)
    if emitter is None:
        raise RuntimeError("Emitter not found for document job")
    certificate = SqlAlchemyCertificateRepository(session).get_active_for_emitter(
        document.emitter_id
    )
    if certificate is None:
        raise RuntimeError("Active certificate not configured")

    job = start_attempt(job, worker_correlation_id=runtime.worker_correlation_id)
    job_repository.save(job)
    logger.info(
        "worker.document_job.started",
        extra=_document_log_fields(job, document),
    )

    certificate_bytes = runtime.certificate_store.decrypt_bytes(
        certificate.encrypted_p12
    )
    certificate_password = runtime.certificate_store.decrypt_text(
        certificate.encrypted_password
    )
    emission_engine, query_gateway = _document_gateways(runtime, document)

    action = select_action(document)
    if action is AttemptAction.PREPARE:
        try:
            stamping = _stamping_for_emission(session, document, runtime)
            prepared = emission_engine.prepare_document(
                document=document,
                emitter=emitter,
                certificate_bytes=certificate_bytes,
                certificate_password=certificate_password,
                stamping=stamping,
            )
        except SifenValidationError as exc:
            recorded = conclude_attempt(
                document,
                job,
                attempt_number=job.attempts,
                result=PreparationRefused(str(exc)),
            )
            return _DocumentJobFinished(
                _persist_document_attempt(session, recorded, publish_status)
            )
        timbrado = read_de_facts(prepared.signed_xml).timbrado or stamping.number
        document = document_repository.save(
            mark_submitting(document, prepared, timbrado=timbrado)
        )
    elif action is AttemptAction.RESEND:
        # Same signed DE (same CDC, signature and dFecFirma) in a new rEnviDe
        # with a fresh dId, stored before it travels (DECISIONES F63, F64).
        request_xml = emission_engine.wrap_signed_document(
            signed_xml=_require_signed_xml(document)
        )
        document = document_repository.save(
            mark_submitting(document, request_xml=request_xml)
        )

    return _ClaimedDocumentAttempt(
        job_id=job.id,
        document_id=document.id,
        attempt_number=job.attempts,
        action=action,
        cdc=document.cdc,
        request_xml=document.sifen_request_xml,
        emitter=emitter,
        certificate_bytes=certificate_bytes,
        certificate_password=certificate_password,
        emission_engine=emission_engine,
        query_gateway=query_gateway,
    )


def _stamping_for_emission(
    session: Session,
    document: Document,
    runtime: _DocumentRuntime,
) -> Stamping:
    """The timbrado active on the emission date (D002) of ``document``.

    DECISIONES F23: chosen with dFeEmiDE in Paraguay time, not the server
    date; D002 before the timbrado start is rejected by SIFEN (1103 as
    amended by NT 01) and a timbrado not active on D002 too (1104, MT v150
    §12.4 p. 160), so both are refused locally.

    Raises:
        SifenValidationError: if no active timbrado covers that date.
    """

    emission_date = resolve_emission_date(document) or runtime.current_date
    stamping = SqlAlchemyStampingRepository(session).get_active_for_emitter(
        document.emitter_id,
        on_date=emission_date,
    )
    if stamping is None:
        raise SifenValidationError(
            "no active timbrado is valid on the emission date (dFeEmiDE) "
            f"{emission_date.isoformat()}; SIFEN rejects it with 1103/1104"
        )
    return stamping


def _require_signed_xml(document: Document) -> str:
    if not document.signed_xml:
        raise RuntimeError("A resend must carry the signed document")
    return document.signed_xml


def _run_document_sifen_step(claim: _ClaimedDocumentAttempt) -> AttemptResult:
    """Talk to SIFEN; every failure becomes a result, none escapes."""

    if claim.action is AttemptAction.RECONCILE:
        return _query_document_by_cdc(claim)
    return _submit_document_request(claim)


def _submit_document_request(claim: _ClaimedDocumentAttempt) -> AttemptResult:
    if claim.request_xml is None:
        raise RuntimeError("A claimed submission must carry its request XML")
    try:
        outcome = claim.emission_engine.submit_prepared(
            request_xml=claim.request_xml,
            emitter=claim.emitter,
            certificate_bytes=claim.certificate_bytes,
            certificate_password=claim.certificate_password,
        )
    except SifenRejectionError as exc:
        return SifenRejected(code=exc.code, message=exc.message)
    except Exception as exc:  # every failure is recorded by the second transaction
        message = describe_submission_failure(exc)
        if request_never_left(exc):
            _log_sifen_failure("worker.document_job.request_not_sent", claim, exc)
            return RequestNotSent(message)
        _log_sifen_failure("worker.document_job.outcome_unknown", claim, exc)
        return OutcomeUnknown(message)
    return SifenAnswered(outcome)


def _query_document_by_cdc(claim: _ClaimedDocumentAttempt) -> AttemptResult:
    if claim.cdc is None:
        raise RuntimeError("A reconciliation attempt must carry the CDC")
    try:
        outcome = claim.query_gateway.query_document(
            emitter=claim.emitter,
            certificate_bytes=claim.certificate_bytes,
            certificate_password=claim.certificate_password,
            cdc=claim.cdc,
        )
    except SifenValidationError as exc:
        return ReconciliationRefused(str(exc))
    except Exception as exc:  # every failure is recorded by the second transaction
        _log_sifen_failure("worker.document_job.query_failed", claim, exc)
        return ReconciliationUnavailable(describe_submission_failure(exc))
    return Reconciled(outcome)


def _record_document_attempt(
    session: Session,
    *,
    claim: _ClaimedDocumentAttempt,
    result: AttemptResult,
    publish_status: _StatusPublisher,
) -> dict[str, str]:
    """Second transaction: record the SIFEN step on the committed rows.

    Locks follow the order every writer uses: emitter, then document, then
    job. Publishing the status webhook locks the emitter, and taking it last
    could deadlock with a first transaction or an operator retry, which hold
    the emitter while they wait on document or job. The emitter wait is not
    bounded: the answer SIFEN gave must not be dropped over a busy emitter.
    """

    SqlAlchemyEmitterRepository(session).lock_row(claim.emitter.id)
    document = _require_row(
        SqlAlchemyDocumentRepository(session).get_for_update(claim.document_id)
    )
    job = _require_row(SqlAlchemyJobRepository(session).get_for_update(claim.job_id))
    recorded = conclude_claimed_attempt(
        current_document=document,
        current_job=job,
        attempt_number=claim.attempt_number,
        result=result,
    )
    if recorded is None:
        logger.warning(
            "worker.document_job.outcome_superseded",
            extra={
                **_document_log_fields(job, document),
                "attempt": claim.attempt_number,
            },
        )
        return _document_job_payload(job, document)
    return _persist_document_attempt(session, recorded, publish_status)


def _persist_document_attempt(
    session: Session,
    recorded: RecordedAttempt,
    publish_status: _StatusPublisher,
) -> dict[str, str]:
    SqlAlchemyDocumentRepository(session).save(recorded.document)
    SqlAlchemyJobRepository(session).save(recorded.job)
    if recorded.retryable:
        _stage_retry_outbox(session, recorded.job)
    if recorded.document_changed:
        publish_status(recorded.document, session)
    if recorded.deadline_alerts:
        logger.warning(
            "worker.document_job.transmission_deadline",
            extra={
                **_document_log_fields(recorded.job, recorded.document),
                "deadline_alerts": [alert.value for alert in recorded.deadline_alerts],
            },
        )
    logger.info(
        "worker.document_job.finished",
        extra={
            **_document_log_fields(recorded.job, recorded.document),
            "job_status": recorded.job.status,
            "document_status": recorded.document.internal_status,
        },
    )
    return _document_job_payload(recorded.job, recorded.document)


def _document_gateways(
    runtime: _DocumentRuntime,
    document: Document,
) -> tuple[DocumentEmissionEngine, SifenQueryGateway]:
    settings = runtime.settings
    sandbox_outcome = SandboxOutcomePolicy(settings.environment).resolve(
        document.payload_snapshot
    )
    query_gateway = runtime.query_gateway
    if query_gateway is None:
        query_gateway = (
            DeterministicSandboxQueryGateway(
                runtime_environment=settings.environment,
                outcome=sandbox_outcome,
            )
            if sandbox_outcome is not None
            else KilaSifenQueryGateway(
                deployment_environment=settings.sifen_environment
            )
        )
    emission_engine = runtime.emission_engine
    if emission_engine is None:
        sandbox_transport = (
            DeterministicSandboxTransport(
                runtime_environment=settings.environment,
                outcome=sandbox_outcome,
            )
            if sandbox_outcome is not None
            else None
        )
        emission_engine = KilaSifenEmissionEngine(
            deployment_environment=settings.sifen_environment,
            transport=sandbox_transport,
        )
    return emission_engine, query_gateway


def _document_job_payload(job: Job, document: Document) -> dict[str, str]:
    return {
        "job_id": job.id,
        "job_type": job.job_type,
        "document_id": document.id,
        "document_type": document.document_type,
        "job_status": job.status,
        "document_status": document.internal_status,
    }


def _document_log_fields(job: Job, document: Document) -> dict[str, str]:
    return {
        "job_id": job.id,
        "document_id": document.id,
        "document_type": document.document_type,
        "emitter_id": document.emitter_id,
    }


def _log_sifen_failure(
    event: str,
    claim: _ClaimedDocumentAttempt,
    exc: Exception,
) -> None:
    logger.warning(
        event,
        extra={
            "job_id": claim.job_id,
            "document_id": claim.document_id,
            "attempt": claim.attempt_number,
            "error_type": type(exc).__name__,
        },
        exc_info=not isinstance(exc, SifenError),
    )


def _require_row(row: _Row | None) -> _Row:
    if row is None:
        raise NotFoundError("jobs.document_context_not_found")
    return row


def process_webhook_delivery_job(
    *,
    job_id: str,
    database_url: str | None = None,
    encryption_key: str | None = None,
    deliverer: WebhookDeliverer | None = None,
) -> dict[str, str | bool]:
    """Process a webhook-delivery job."""

    settings = get_settings()
    database_url, encryption_key = _worker_runtime_secrets(
        database_url=database_url,
        encryption_key=encryption_key,
    )
    ensure_worker_observability()
    correlation_token, worker_correlation_id = _bind_worker_correlation_id()
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    deliverer = deliverer or WebhookDeliverer(
        url_policy=WebhookUrlPolicy.for_environment(settings.environment)
    )
    secret_store = EncryptedCertificateStore(encryption_key)

    try:
        with session_scope(session_factory) as session:
            job = SqlAlchemyJobRepository(session).get(job_id)
            if job is not None:
                logger.info(
                    "worker.webhook_delivery_job.started",
                    extra={
                        "job_id": job.id,
                        "delivery_id": job.related_entity_id,
                        "emitter_id": job.emitter_id,
                    },
                )
                SqlAlchemyJobRepository(session).save(
                    replace(job, worker_correlation_id=worker_correlation_id)
                )

            service = WebhookService(
                webhook_repository=SqlAlchemyWebhookRepository(session),
                emitter_repository=SqlAlchemyEmitterRepository(session, secret_store),
                job_repository=SqlAlchemyJobRepository(session),
                secret_store=secret_store,
                queue=_NoopWebhookQueue(),
                deliverer=deliverer,
            )
            payload = service.process_delivery_attempt(job_id=job_id)
            if payload["retryable"]:
                retry_job = SqlAlchemyJobRepository(session).get(job_id)
                if retry_job is None:
                    raise RuntimeError("Persisted webhook retry job is missing")
                _stage_retry_outbox(session, retry_job)
            logger.info(
                "worker.webhook_delivery_job.finished",
                extra={
                    "job_id": payload["job_id"],
                    "delivery_id": payload["delivery_id"],
                    "job_status": payload["job_status"],
                    "delivery_status": payload["delivery_status"],
                },
            )
        return payload
    finally:
        if correlation_token is not None:
            reset_correlation_id(correlation_token)


def process_event_job(
    *,
    job_id: str,
    database_url: str | None = None,
    encryption_key: str | None = None,
    submission_gateway: EventSubmissionGateway | None = None,
    webhook_queue=None,
) -> dict[str, str | bool | None]:
    """Run one attempt of a fiscal event job outside the HTTP request.

    Like documents, the exact request is committed before SIFEN is called and
    the outcome is recorded in a second transaction; nothing is held while
    SIFEN answers.
    """

    settings = get_settings()
    database_url, encryption_key = _worker_runtime_secrets(
        database_url=database_url,
        encryption_key=encryption_key,
    )
    ensure_worker_observability()
    correlation_token, worker_correlation_id = _bind_worker_correlation_id()
    session_factory = build_session_factory(build_engine(database_url))
    certificate_store = EncryptedCertificateStore(encryption_key)
    submission_gateway = submission_gateway or KilaSifenEventGateway(
        settings.sifen_environment
    )

    def event_service(session: Session) -> EventService:
        return _build_event_service(
            session,
            settings=settings,
            certificate_store=certificate_store,
            submission_gateway=submission_gateway,
            webhook_queue=webhook_queue,
            database_url=database_url,
            encryption_key=encryption_key,
        )

    try:
        with (
            _retry_later_if_emitter_busy(session_factory, job_id),
            session_scope(session_factory) as session,
        ):
            claim = event_service(session).begin_queued_event_attempt(
                job_id=job_id,
                worker_correlation_id=worker_correlation_id,
            )
            if isinstance(claim, DeferredEventJob):
                _stage_dispatch(session, claim.job)
        if isinstance(claim, (FinishedEventJob, DeferredEventJob)):
            payload = claim.payload
        else:
            # The request is committed: nothing is held while SIFEN answers.
            result = send_event_attempt(submission_gateway, claim)
            with session_scope(session_factory) as session:
                payload = event_service(session).record_event_attempt(
                    attempt=claim,
                    result=result,
                )
                if payload["retryable"]:
                    _schedule_event_retry(session, job_id)
        logger.info(
            "worker.event_job.finished",
            extra={
                "job_id": payload["job_id"],
                "event_id": payload["event_id"],
                "event_type": payload["event_type"],
                "job_status": payload["job_status"],
                "event_status": payload["event_status"],
            },
        )
        return payload
    finally:
        _drop_cached_signing_keys()
        if correlation_token is not None:
            reset_correlation_id(correlation_token)


def _build_event_service(
    session: Session,
    *,
    settings: Settings,
    certificate_store: EncryptedCertificateStore,
    submission_gateway: EventSubmissionGateway,
    webhook_queue,
    database_url: str,
    encryption_key: str,
) -> EventService:
    job_repository = SqlAlchemyJobRepository(session)
    webhook_publisher = None
    if settings.document_publish_webhooks:
        webhook_publisher = SavepointWebhookPublisher(
            session,
            WebhookService(
                webhook_repository=SqlAlchemyWebhookRepository(session),
                emitter_repository=SqlAlchemyEmitterRepository(
                    session, certificate_store
                ),
                job_repository=job_repository,
                secret_store=certificate_store,
                queue=webhook_queue or _build_webhook_outbox(session),
                deliverer=WebhookDeliverer(
                    url_policy=WebhookUrlPolicy.for_environment(settings.environment)
                ),
                database_url=database_url,
                encryption_key=encryption_key,
            ),
        )
    return EventService(
        event_repository=SqlAlchemyEventRepository(session),
        emitter_repository=SqlAlchemyEmitterRepository(session, certificate_store),
        document_repository=SqlAlchemyDocumentRepository(session),
        certificate_repository=SqlAlchemyCertificateRepository(session),
        job_repository=job_repository,
        certificate_store=certificate_store,
        submission_gateway=submission_gateway,
        inutilized_range_repository=SqlAlchemyInutilizedNumberRangeRepository(
            session
        ),
        webhook_publisher=webhook_publisher,
    )


def _schedule_event_retry(session: Session, job_id: str) -> None:
    job_repository = SqlAlchemyJobRepository(session)
    retry_job = job_repository.get(job_id)
    if retry_job is None:
        raise RuntimeError("Persisted event retry job is missing")
    retry_job = replace(
        retry_job,
        scheduled_at=_retry_at(
            attempt_number=retry_job.attempts,
            delays=_EVENT_RETRY_DELAYS,
        ),
        updated_at=_now(),
    )
    job_repository.save(retry_job)
    _stage_retry_outbox(session, retry_job)


class _NoopWebhookQueue:
    def enqueue_webhook_delivery(self, *args, **kwargs):
        del args, kwargs
        return None


class WebhookDeliveryRetryableError(RuntimeError):
    """Legacy compatibility alias for callers of the former RQ retry path."""


class DocumentEmissionRetryableError(RuntimeError):
    """Legacy compatibility alias for callers of the former RQ retry path."""


class EventSubmissionRetryableError(RuntimeError):
    """Legacy compatibility alias for callers of the former RQ retry path."""


def _drop_cached_signing_keys() -> None:
    """Evict decrypted PKCS12 keys once a signing job ends.

    The engine keeps decoded signers in a per-process LRU. A worker that runs
    jobs in its own process (``SimpleWorker``, used on Windows) would
    otherwise keep the private key of a certificate that was replaced or
    deactivated until LRU eviction or restart. Forking workers lose the cache
    with the work horse anyway, so the next job pays one PKCS12 decode.
    """

    clear_pkcs12_signer_cache()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _retry_at(*, attempt_number: int, delays: tuple[int, ...]) -> datetime:
    retry_index = min(max(attempt_number - 1, 0), len(delays) - 1)
    return _now() + timedelta(seconds=delays[retry_index])


@contextmanager
def _retry_later_if_emitter_busy(session_factory, job_id: str) -> Iterator[None]:
    """Put the job back in line when its emitter row stayed locked.

    The first transaction of an attempt waits a bounded time for the emitter
    lock (``emitters.lock_timeout``). Nothing was sent and no attempt was
    spent, so only the schedule moves: the job keeps its status and is staged
    again for a little later, and the error is re-raised for RQ to report.

    Keeping the status matters: a ``queued`` job on a ``failed`` document or
    event is an operator retry, and only a ``queued`` job reopens one.
    """

    try:
        yield
    except ServiceUnavailableError:
        logger.warning("worker.job.emitter_busy", extra={"job_id": job_id})
        with session_scope(session_factory) as session:
            jobs = SqlAlchemyJobRepository(session)
            job = jobs.get_for_update(job_id)
            if job is not None and job.status in _WAITING_JOB_STATUSES:
                job = jobs.save(
                    replace(
                        job,
                        scheduled_at=_now()
                        + timedelta(seconds=_EMITTER_BUSY_RETRY_SECONDS),
                        error_snapshot={
                            "category": "emitter_busy",
                            "message": "emitters.lock_timeout",
                        },
                        updated_at=_now(),
                    )
                )
                _stage_dispatch(session, job)
        raise


def _stage_retry_outbox(session, job: Job) -> None:
    """Persist the next attempt in the same transaction as its retry state."""

    if job.status != "retry_scheduled" or job.scheduled_at is None:
        raise RuntimeError("Retry jobs require a durable schedule")
    _stage_dispatch(session, job)


def _stage_dispatch(session, job: Job) -> None:
    """Stage ``job`` in the outbox for dispatch at its ``scheduled_at``."""

    queue = SqlAlchemyJobOutboxQueue(SqlAlchemyJobOutboxRepository(session))
    if job.job_type == "document.emit":
        queue.enqueue_document_emit(job)
    elif job.job_type == "event.submit":
        queue.enqueue_event_submit(job)
    elif job.job_type == "webhook.deliver":
        queue.enqueue_webhook_delivery(job)
    else:
        raise RuntimeError(f"Unsupported retry job type: {job.job_type}")


def _worker_runtime_secrets(
    *,
    database_url: str | None,
    encryption_key: str | None,
) -> tuple[str, str]:
    """Resolve secrets in worker memory without accepting them from Redis jobs."""

    settings = get_settings()
    resolved_key = encryption_key or settings.encryption_key
    if not resolved_key:
        raise RuntimeError("KILA_SIFEN_ENCRYPTION_KEY is required by workers")
    return database_url or settings.database_url, resolved_key


def _publish_document_status_webhooks(
    *,
    document,
    session,
    database_url: str,
    encryption_key: str,
    webhook_queue,
) -> None:
    settings = get_settings()
    if not settings.document_publish_webhooks:
        return

    queue_adapter = webhook_queue or _build_webhook_outbox(session)
    publisher = SavepointWebhookPublisher(
        session,
        WebhookService(
            webhook_repository=SqlAlchemyWebhookRepository(session),
            emitter_repository=SqlAlchemyEmitterRepository(
                session, EncryptedCertificateStore(encryption_key)
            ),
            job_repository=SqlAlchemyJobRepository(session),
            secret_store=EncryptedCertificateStore(encryption_key),
            queue=queue_adapter,
            deliverer=WebhookDeliverer(
                url_policy=WebhookUrlPolicy.for_environment(settings.environment)
            ),
            database_url=database_url,
            encryption_key=encryption_key,
        ),
    )
    try:
        publisher.publish_document_status(document=document)
    except Exception:
        logger.exception(
            "document_webhook_publish_failed",
            extra={
                "document_id": document.id,
                "emitter_id": document.emitter_id,
                "internal_status": document.internal_status,
            },
        )


def _build_webhook_outbox(session) -> SqlAlchemyJobOutboxQueue:
    return SqlAlchemyJobOutboxQueue(SqlAlchemyJobOutboxRepository(session))


def _bind_worker_correlation_id() -> tuple[object | None, str | None]:
    correlation_id = get_correlation_id()
    rq_job = get_current_job()
    if rq_job is not None:
        correlation_id = rq_job.meta.get("correlation_id") or correlation_id
    if correlation_id is None:
        return None, None
    return set_correlation_id(correlation_id), correlation_id
