"""Worker entrypoints for background jobs."""

import logging
from dataclasses import replace
from datetime import UTC, date, datetime
from xml.etree import ElementTree as ET

from redis import Redis
from rq import Queue, Retry, get_current_job

from kilasifen.application.events.service import EventService
from kilasifen.application.jobs.service import JobService
from kilasifen.application.sandbox.service import SandboxOutcomePolicy
from kilasifen.application.webhooks.service import WebhookService
from kilasifen.config import get_settings
from kilasifen.domain.common.fiscal_states import (
    DOCUMENT_TERMINAL_STATUSES,
    job_status_for_document,
)
from kilasifen.domain.documents.models import Document
from kilasifen.domain.jobs.models import Job
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
from kilasifen.infrastructure.sandbox.query import DeterministicSandboxQueryGateway
from kilasifen.infrastructure.sandbox.transport import DeterministicSandboxTransport
from kilasifen.infrastructure.sifen.engine import (
    DocumentEmissionEngine,
    EmissionOutcome,
    EmissionTransportUncertainError,
    PysifenEmissionEngine,
)
from kilasifen.infrastructure.sifen.event import (
    EventSubmissionGateway,
    PysifenEventGateway,
)
from kilasifen.infrastructure.sifen.query import (
    DocumentQueryOutcome,
    PysifenQueryGateway,
    SifenQueryGateway,
)
from kilasifen.infrastructure.webhooks.deliverer import WebhookDeliverer
from kilasifen.infrastructure.webhooks.security import WebhookUrlPolicy
from kilasifen.logging import (
    get_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from kilasifen.observability import ensure_worker_observability
from pysifen.sdk.errors import (
    SifenRejectionError,
    SifenTimeoutError,
    SifenTransportError,
    SifenValidationError,
)

logger = logging.getLogger(__name__)

_MAX_DOCUMENT_ATTEMPTS = 5


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
    """Process a document-emission job using the configured engine."""

    settings = get_settings()
    database_url, encryption_key = _worker_runtime_secrets(
        database_url=database_url,
        encryption_key=encryption_key,
    )
    ensure_worker_observability()
    correlation_token, worker_correlation_id = _bind_worker_correlation_id()
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    certificate_store = EncryptedCertificateStore(encryption_key)
    retryable = False
    payload: dict[str, str]

    try:
        with session_scope(session_factory) as session:
            job_repository = SqlAlchemyJobRepository(session)
            job_service = JobService(job_repository)
            document_repository = SqlAlchemyDocumentRepository(session)
            emitter_repository = SqlAlchemyEmitterRepository(session, certificate_store)
            certificate_repository = SqlAlchemyCertificateRepository(session)
            stamping_repository = SqlAlchemyStampingRepository(session)
            job, document = job_service.get_document_job_context(
                job_id=job_id,
                document_repository=document_repository,
            )
            sandbox_outcome = SandboxOutcomePolicy(settings.environment).resolve(
                document.payload_snapshot
            )
            if query_gateway is None:
                query_gateway = (
                    DeterministicSandboxQueryGateway(
                        runtime_environment=settings.environment,
                        outcome=sandbox_outcome,
                    )
                    if sandbox_outcome is not None
                    else PysifenQueryGateway(
                        deployment_environment=settings.sifen_environment
                    )
                )
            if emission_engine is None:
                sandbox_transport = (
                    DeterministicSandboxTransport(
                        runtime_environment=settings.environment,
                        outcome=sandbox_outcome,
                    )
                    if sandbox_outcome is not None
                    else None
                )
                emission_engine = PysifenEmissionEngine(
                    deployment_environment=settings.sifen_environment,
                    transport=sandbox_transport,
                )
            if document.internal_status in DOCUMENT_TERMINAL_STATUSES and not (
                document.internal_status == "failed" and job.status == "queued"
            ):
                return {
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "document_id": document.id,
                    "document_type": document.document_type,
                    "job_status": job.status,
                    "document_status": document.internal_status,
                }
            attempt_number = job.attempts + 1
            job = replace(
                job,
                status="processing",
                attempts=attempt_number,
                started_at=_now(),
                finished_at=None,
                worker_correlation_id=worker_correlation_id,
                updated_at=_now(),
            )
            job_repository.save(job)
            emitter = emitter_repository.get(document.emitter_id)
            if emitter is None:
                raise RuntimeError("Emitter not found for document job")
            certificate = certificate_repository.get_active_for_emitter(
                document.emitter_id
            )
            if certificate is None:
                raise RuntimeError("Active certificate not configured")
            logger.info(
                "worker.document_job.started",
                extra={
                    "job_id": job.id,
                    "document_id": document.id,
                    "document_type": document.document_type,
                    "emitter_id": document.emitter_id,
                },
            )

            certificate_bytes = certificate_store.decrypt_bytes(
                certificate.encrypted_p12
            )
            certificate_password = certificate_store.decrypt_text(
                certificate.encrypted_password
            )

            try:
                reconciliation = _reconcile_before_resubmission(
                    document=document,
                    emitter=emitter,
                    certificate_bytes=certificate_bytes,
                    certificate_password=certificate_password,
                    query_gateway=query_gateway,
                )
                if reconciliation is None:
                    stamping = stamping_repository.get_active_for_emitter(
                        document.emitter_id,
                        on_date=current_date or date.today(),
                    )
                    if stamping is None:
                        raise RuntimeError("Active stamping not configured")
                    outcome = emission_engine.emit_document(
                        document=document,
                        emitter=emitter,
                        certificate=certificate,
                        certificate_bytes=certificate_bytes,
                        certificate_password=certificate_password,
                        stamping=stamping,
                    )
                    updated_document = _apply_emission_outcome(document, outcome)
                else:
                    updated_document = _apply_reconciliation_outcome(
                        document,
                        reconciliation,
                    )

                orchestration_status = job_status_for_document(
                    updated_document.internal_status
                )
                if orchestration_status == "failed":
                    updated_job = replace(
                        job,
                        status="failed",
                        error_snapshot={
                            "category": "sifen_rejection",
                            "code": updated_document.sifen_result_code,
                            "message": updated_document.sifen_result_message,
                        },
                        worker_correlation_id=worker_correlation_id,
                    )
                elif orchestration_status == "succeeded":
                    updated_job = replace(
                        job,
                        status="succeeded",
                        error_snapshot=None,
                        worker_correlation_id=worker_correlation_id,
                    )
                else:
                    retryable = True
                    pending_category = (
                        "reconciliation_pending"
                        if reconciliation is not None
                        else "sifen_pending"
                    )
                    updated_job = replace(
                        job,
                        status="retry_scheduled",
                        error_snapshot={
                            "category": pending_category,
                            "code": updated_document.sifen_result_code,
                            "message": updated_document.sifen_result_message,
                        },
                        worker_correlation_id=worker_correlation_id,
                    )
            except EmissionTransportUncertainError as exc:
                retryable = True
                updated_document = replace(
                    document,
                    generated_xml=exc.generated_xml,
                    signed_xml=exc.signed_xml,
                    sifen_request_xml=exc.request_xml,
                    cdc=exc.cdc or document.cdc,
                    internal_status="retry_pending",
                    sifen_status="retry_pending",
                    sifen_result_message=str(exc),
                )
                updated_job = replace(
                    job,
                    status="retry_scheduled",
                    error_snapshot={"category": "transport", "message": str(exc)},
                    worker_correlation_id=worker_correlation_id,
                )
            except SifenValidationError as exc:
                updated_document = replace(document, internal_status="failed")
                updated_job = replace(
                    job,
                    status="failed",
                    error_snapshot={
                        "category": "fiscal_validation",
                        "message": str(exc),
                    },
                    worker_correlation_id=worker_correlation_id,
                )
            except (SifenTimeoutError, SifenTransportError) as exc:
                retryable = True
                updated_document = replace(document, internal_status="retry_pending")
                updated_job = replace(
                    job,
                    status="retry_scheduled",
                    error_snapshot={"category": "transport", "message": str(exc)},
                    worker_correlation_id=worker_correlation_id,
                )
            except SifenRejectionError as exc:
                updated_document = replace(
                    document,
                    internal_status="rejected",
                    sifen_status="rejected",
                    sifen_result_code=exc.code,
                    sifen_result_message=exc.message,
                )
                updated_job = replace(
                    job,
                    status="failed",
                    error_snapshot={
                        "category": "sifen_rejection",
                        "code": exc.code,
                        "message": exc.message,
                    },
                    worker_correlation_id=worker_correlation_id,
                )

            if retryable and attempt_number >= _MAX_DOCUMENT_ATTEMPTS:
                retryable = False
                if _is_reconciliation_pending(updated_job):
                    updated_document, updated_job = _mark_reconciliation_required(
                        document=updated_document,
                        job=updated_job,
                    )
                else:
                    updated_document = replace(
                        updated_document,
                        internal_status="failed",
                        sifen_status="failed",
                        sifen_result_message="document retry attempts exhausted",
                    )
                    updated_job = replace(
                        updated_job,
                        status="failed",
                        error_snapshot={
                            "category": "retry_exhausted",
                            "message": "document retry attempts exhausted",
                        },
                        finished_at=_now(),
                        updated_at=_now(),
                    )
            elif updated_job.status in {"succeeded", "failed"}:
                updated_job = replace(
                    updated_job,
                    finished_at=_now(),
                    updated_at=_now(),
                )

            document_repository.save(updated_document)
            job_repository.save(updated_job)
            _publish_document_status_webhooks(
                document=updated_document,
                session=session,
                database_url=database_url,
                encryption_key=encryption_key,
                webhook_queue=webhook_queue,
            )
            logger.info(
                "worker.document_job.finished",
                extra={
                    "job_id": updated_job.id,
                    "document_id": updated_document.id,
                    "document_type": updated_document.document_type,
                    "emitter_id": updated_document.emitter_id,
                    "job_status": updated_job.status,
                    "document_status": updated_document.internal_status,
                },
            )

            payload = {
                "job_id": updated_job.id,
                "job_type": updated_job.job_type,
                "document_id": updated_document.id,
                "document_type": updated_document.document_type,
                "job_status": updated_job.status,
                "document_status": updated_document.internal_status,
            }
        if retryable:
            raise DocumentEmissionRetryableError(
                "document emission requires retry or reconciliation"
            )
        return payload
    finally:
        if correlation_token is not None:
            reset_correlation_id(correlation_token)


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
            logger.info(
                "worker.webhook_delivery_job.finished",
                extra={
                    "job_id": payload["job_id"],
                    "delivery_id": payload["delivery_id"],
                    "job_status": payload["job_status"],
                    "delivery_status": payload["delivery_status"],
                },
            )
        if payload["retryable"]:
            raise WebhookDeliveryRetryableError("webhook delivery scheduled for retry")
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
    """Process one persisted fiscal event outside the HTTP request lifecycle."""

    settings = get_settings()
    database_url, encryption_key = _worker_runtime_secrets(
        database_url=database_url,
        encryption_key=encryption_key,
    )
    ensure_worker_observability()
    correlation_token, worker_correlation_id = _bind_worker_correlation_id()
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    certificate_store = EncryptedCertificateStore(encryption_key)
    submission_gateway = submission_gateway or PysifenEventGateway(
        settings.sifen_environment
    )
    retryable = False

    try:
        with session_scope(session_factory) as session:
            job_repository = SqlAlchemyJobRepository(session)
            job = job_repository.get(job_id)
            if job is not None:
                job_repository.save(
                    replace(job, worker_correlation_id=worker_correlation_id)
                )

            webhook_publisher = None
            if settings.document_publish_webhooks:
                queue_adapter = webhook_queue or _build_webhook_queue(
                    settings.redis_url
                )
                webhook_publisher = WebhookService(
                    webhook_repository=SqlAlchemyWebhookRepository(session),
                    emitter_repository=SqlAlchemyEmitterRepository(
                        session, certificate_store
                    ),
                    job_repository=job_repository,
                    secret_store=certificate_store,
                    queue=queue_adapter,
                    deliverer=WebhookDeliverer(
                        url_policy=WebhookUrlPolicy.for_environment(
                            settings.environment
                        )
                    ),
                    database_url=database_url,
                    encryption_key=encryption_key,
                )

            service = EventService(
                event_repository=SqlAlchemyEventRepository(session),
                emitter_repository=SqlAlchemyEmitterRepository(
                    session, certificate_store
                ),
                document_repository=SqlAlchemyDocumentRepository(session),
                certificate_repository=SqlAlchemyCertificateRepository(session),
                job_repository=job_repository,
                certificate_store=certificate_store,
                submission_gateway=submission_gateway,
                inutilized_range_repository=(
                    SqlAlchemyInutilizedNumberRangeRepository(session)
                ),
                webhook_publisher=webhook_publisher,
            )
            payload = service.process_queued_event(job_id=job_id)
            retryable = bool(payload["retryable"])
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
        if retryable:
            raise EventSubmissionRetryableError(
                "event submission requires a bounded retry"
            )
        return payload
    finally:
        if correlation_token is not None:
            reset_correlation_id(correlation_token)


class _NoopWebhookQueue:
    def enqueue_webhook_delivery(self, *args, **kwargs):
        del args, kwargs
        return None


class WebhookDeliveryRetryableError(RuntimeError):
    """Signal RQ to apply the configured bounded retry schedule."""


class DocumentEmissionRetryableError(RuntimeError):
    """Signal RQ to retry a transport-uncertain fiscal document safely."""


class EventSubmissionRetryableError(RuntimeError):
    """Signal RQ to retry a transport-uncertain fiscal event safely."""


def _reconcile_before_resubmission(
    *,
    document,
    emitter,
    certificate_bytes: bytes,
    certificate_password: str,
    query_gateway: SifenQueryGateway,
) -> DocumentQueryOutcome | None:
    if (
        document.internal_status
        not in {"retry_pending", "submitted", "reconciliation_required"}
        or not document.cdc
    ):
        return None

    return query_gateway.query_document(
        emitter=emitter,
        certificate_bytes=certificate_bytes,
        certificate_password=certificate_password,
        cdc=document.cdc,
    )


def _apply_emission_outcome(
    document: Document,
    outcome: EmissionOutcome,
) -> Document:
    return replace(
        document,
        generated_xml=outcome.generated_xml,
        signed_xml=outcome.signed_xml,
        sifen_request_xml=outcome.request_xml,
        sifen_response_raw=outcome.response_raw,
        internal_status=outcome.sifen_status,
        sifen_status=outcome.sifen_status,
        sifen_result_code=outcome.result_code,
        sifen_result_message=outcome.result_message,
        cdc=outcome.cdc
        or _extract_cdc(
            outcome.signed_xml,
            outcome.generated_xml,
        ),
        updated_at=_now(),
    )


def _apply_reconciliation_outcome(
    document: Document,
    outcome: DocumentQueryOutcome,
) -> Document:
    traced_document = replace(
        document,
        last_query_request_xml=outcome.request_xml,
        last_query_response_raw=outcome.response_raw,
        last_query_at=_now(),
        sifen_result_code=outcome.result_code,
        sifen_result_message=outcome.result_message,
        updated_at=_now(),
    )
    if outcome.status != "found":
        # SIFEN code 0420 combines "not found" and "not approved". It is not
        # proof that the previous submission failed, so resending here could
        # duplicate one fiscal intent. Keep querying the immutable CDC instead.
        return replace(
            traced_document,
            internal_status="retry_pending",
            sifen_status="retry_pending",
        )

    signed_xml = outcome.content_xml or document.signed_xml
    if not signed_xml:
        raise SifenValidationError("SIFEN returned a document without XML content")
    return replace(
        traced_document,
        signed_xml=signed_xml,
        internal_status="approved",
        sifen_status="approved",
    )


def _is_reconciliation_pending(job: Job) -> bool:
    snapshot = job.error_snapshot or {}
    return snapshot.get("category") == "reconciliation_pending"


def _mark_reconciliation_required(
    *,
    document: Document,
    job: Job,
) -> tuple[Document, Job]:
    message = (
        "automatic reconciliation attempts exhausted; "
        "the immutable CDC was not resubmitted"
    )
    return (
        replace(
            document,
            internal_status="reconciliation_required",
            sifen_status="reconciliation_required",
            sifen_result_message=message,
            updated_at=_now(),
        ),
        replace(
            job,
            status="failed",
            error_snapshot={
                "category": "reconciliation_required",
                "code": document.sifen_result_code,
                "message": message,
            },
            finished_at=_now(),
            updated_at=_now(),
        ),
    )


def _now() -> datetime:
    return datetime.now(UTC)


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

    queue_adapter = webhook_queue or _build_webhook_queue(settings.redis_url)
    service = WebhookService(
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
    )
    try:
        service.publish_document_status(document=document)
    except Exception:
        logger.exception(
            "document_webhook_publish_failed",
            extra={
                "document_id": document.id,
                "emitter_id": document.emitter_id,
                "internal_status": document.internal_status,
            },
        )


def _build_webhook_queue(redis_url: str):
    queue = Queue("webhooks", connection=Redis.from_url(redis_url))
    return _WebhookRqQueue(queue)


class _WebhookRqQueue:
    def __init__(self, queue: Queue):
        self.queue = queue

    def enqueue_webhook_delivery(self, job, *, database_url: str, encryption_key: str):
        del database_url, encryption_key
        return self.queue.enqueue_call(
            func=process_webhook_delivery_job,
            kwargs={"job_id": job.id},
            job_id=job.id,
            meta={"correlation_id": get_correlation_id()},
            retry=Retry(max=7, interval=[10, 30, 120, 300, 900, 1800, 3600]),
        )


def _bind_worker_correlation_id() -> tuple[object | None, str | None]:
    correlation_id = get_correlation_id()
    rq_job = get_current_job()
    if rq_job is not None:
        correlation_id = rq_job.meta.get("correlation_id") or correlation_id
    if correlation_id is None:
        return None, None
    return set_correlation_id(correlation_id), correlation_id


def _extract_cdc(*xml_candidates: str | None) -> str | None:
    for xml_text in xml_candidates:
        if not xml_text:
            continue
        try:
            root = ET.fromstring(xml_text.encode("utf-8"))
        except ET.ParseError:
            continue
        for element in root.iter():
            if element.tag.endswith("DE"):
                return element.attrib.get("Id")
    return None
