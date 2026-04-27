"""Worker entrypoints for background jobs."""

import logging
from dataclasses import replace
from datetime import date
from xml.etree import ElementTree as ET

from redis import Redis
from rq import Queue, get_current_job

from kilasifen.application.jobs.service import JobService
from kilasifen.application.webhooks.service import WebhookService
from kilasifen.config import get_settings
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
from kilasifen.infrastructure.sifen.engine import (
    DocumentEmissionEngine,
    PysifenEmissionEngine,
)
from kilasifen.infrastructure.webhooks.deliverer import WebhookDeliverer
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


def process_document_job(
    *,
    job_id: str,
    database_url: str,
    encryption_key: str,
    emission_engine: DocumentEmissionEngine | None = None,
    current_date: date | None = None,
    webhook_queue=None,
) -> dict[str, str]:
    """Process a document-emission job using the configured engine."""

    ensure_worker_observability()
    correlation_token, worker_correlation_id = _bind_worker_correlation_id()
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    emission_engine = emission_engine or PysifenEmissionEngine()
    certificate_store = EncryptedCertificateStore(encryption_key)

    try:
        with session_scope(session_factory) as session:
            job_repository = SqlAlchemyJobRepository(session)
            job_service = JobService(job_repository)
            document_repository = SqlAlchemyDocumentRepository(session)
            emitter_repository = SqlAlchemyEmitterRepository(session)
            certificate_repository = SqlAlchemyCertificateRepository(session)
            stamping_repository = SqlAlchemyStampingRepository(session)
            job, document = job_service.get_document_job_context(
                job_id=job_id,
                document_repository=document_repository,
            )
            emitter = emitter_repository.get(document.emitter_id)
            if emitter is None:
                raise RuntimeError("Emitter not found for document job")
            certificate = certificate_repository.get_active_for_emitter(
                document.emitter_id
            )
            if certificate is None:
                raise RuntimeError("Active certificate not configured")
            stamping = stamping_repository.get_active_for_emitter(
                document.emitter_id,
                on_date=current_date or date.today(),
            )
            if stamping is None:
                raise RuntimeError("Active stamping not configured")

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
                outcome = emission_engine.emit_document(
                    document=document,
                    emitter=emitter,
                    certificate=certificate,
                    certificate_bytes=certificate_bytes,
                    certificate_password=certificate_password,
                    stamping=stamping,
                )
                updated_document = replace(
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
                )
                if outcome.sifen_status == "rejected":
                    updated_job = replace(
                        job,
                        status="failed",
                        error_snapshot={
                            "category": "sifen_rejection",
                            "code": outcome.result_code,
                            "message": outcome.result_message,
                        },
                        worker_correlation_id=worker_correlation_id,
                    )
                else:
                    updated_job = replace(
                        job,
                        status="succeeded",
                        error_snapshot=None,
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

            return {
                "job_id": updated_job.id,
                "job_type": updated_job.job_type,
                "document_id": updated_document.id,
                "document_type": updated_document.document_type,
                "job_status": updated_job.status,
                "document_status": updated_document.internal_status,
            }
    finally:
        if correlation_token is not None:
            reset_correlation_id(correlation_token)


def process_webhook_delivery_job(
    *,
    job_id: str,
    database_url: str,
    encryption_key: str,
    deliverer: WebhookDeliverer | None = None,
) -> dict[str, str]:
    """Process a webhook-delivery job."""

    ensure_worker_observability()
    correlation_token, worker_correlation_id = _bind_worker_correlation_id()
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)
    deliverer = deliverer or WebhookDeliverer()
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
                emitter_repository=SqlAlchemyEmitterRepository(session),
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
            return payload
    finally:
        if correlation_token is not None:
            reset_correlation_id(correlation_token)


class _NoopWebhookQueue:
    def enqueue_webhook_delivery(self, *args, **kwargs):
        del args, kwargs
        return None


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
        emitter_repository=SqlAlchemyEmitterRepository(session),
        job_repository=SqlAlchemyJobRepository(session),
        secret_store=EncryptedCertificateStore(encryption_key),
        queue=queue_adapter,
        deliverer=WebhookDeliverer(),
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
        return self.queue.enqueue_call(
            func=process_webhook_delivery_job,
            kwargs={
                "job_id": job.id,
                "database_url": database_url,
                "encryption_key": encryption_key,
            },
            job_id=job.id,
            meta={"correlation_id": get_correlation_id()},
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
