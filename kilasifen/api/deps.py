"""Shared API dependencies."""

from collections.abc import Callable, Generator

from fastapi import Depends, Header, Request
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from kilasifen.application.admin.service import AdminConsoleService
from kilasifen.application.documents.service import DocumentService
from kilasifen.application.emitters.health import EmitterHealthService
from kilasifen.application.events.service import EventService
from kilasifen.application.jobs.service import JobService
from kilasifen.application.queries.service import QueryService
from kilasifen.application.stampings.service import StampingService
from kilasifen.application.webhooks.service import WebhookService
from kilasifen.application.certificates.service import CertificateService
from kilasifen.application.emitters.service import EmitterService
from kilasifen.config import get_settings
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.repositories.documents import SqlAlchemyDocumentRepository
from kilasifen.infrastructure.db.repositories.events import SqlAlchemyEventRepository
from kilasifen.infrastructure.db.repositories.certificates import (
    SqlAlchemyCertificateRepository,
)
from kilasifen.infrastructure.db.repositories.emitters import SqlAlchemyEmitterRepository
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.repositories.stampings import SqlAlchemyStampingRepository
from kilasifen.infrastructure.db.repositories.webhooks import SqlAlchemyWebhookRepository
from kilasifen.infrastructure.db.session import session_scope
from kilasifen.infrastructure.jobs.queue import RqJobQueue
from kilasifen.infrastructure.sifen.event import PysifenEventGateway
from kilasifen.infrastructure.sifen.query import PysifenQueryGateway
from kilasifen.infrastructure.webhooks.deliverer import WebhookDeliverer
from kilasifen.security import ApiKeyPrincipal, validate_api_key


def get_api_key_principal(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> ApiKeyPrincipal:
    """Resolve and validate the caller API key."""

    return validate_api_key(x_api_key)


RequireApiKey = Callable[..., ApiKeyPrincipal]


def get_db_session(request: Request) -> Generator[Session, None, None]:
    """Provide a database session for request handlers."""

    session_factory = request.app.state.session_factory
    with session_scope(session_factory) as session:
        yield session


def get_emitter_service(session: Session = Depends(get_db_session)) -> EmitterService:
    """Build the emitter application service for one request."""

    repository = SqlAlchemyEmitterRepository(session)
    return EmitterService(repository)


def get_emitter_health_service(
    session: Session = Depends(get_db_session),
) -> EmitterHealthService:
    """Build the emitter-health service for one request."""

    return EmitterHealthService(
        emitter_repository=SqlAlchemyEmitterRepository(session),
        certificate_repository=SqlAlchemyCertificateRepository(session),
        stamping_repository=SqlAlchemyStampingRepository(session),
        document_repository=SqlAlchemyDocumentRepository(session),
        job_repository=SqlAlchemyJobRepository(session),
    )


def get_certificate_service(
    session: Session = Depends(get_db_session),
) -> CertificateService:
    """Build the certificate application service for one request."""

    settings = get_settings()
    if not settings.encryption_key:
        raise RuntimeError("KILA_SIFEN_ENCRYPTION_KEY is required for certificates.")

    emitter_repository = SqlAlchemyEmitterRepository(session)
    certificate_repository = SqlAlchemyCertificateRepository(session)
    certificate_store = EncryptedCertificateStore(settings.encryption_key)
    return CertificateService(
        certificate_repository=certificate_repository,
        emitter_repository=emitter_repository,
        certificate_store=certificate_store,
    )


def get_stamping_service(
    session: Session = Depends(get_db_session),
) -> StampingService:
    """Build the stamping application service for one request."""

    emitter_repository = SqlAlchemyEmitterRepository(session)
    stamping_repository = SqlAlchemyStampingRepository(session)
    return StampingService(
        stamping_repository=stamping_repository,
        emitter_repository=emitter_repository,
    )


def get_job_service(session: Session = Depends(get_db_session)) -> JobService:
    """Build the job application service for one request."""

    repository = SqlAlchemyJobRepository(session)
    return JobService(repository)


def get_document_service(
    session: Session = Depends(get_db_session),
) -> DocumentService:
    """Build the document application service for one request."""

    settings = get_settings()
    emitter_repository = SqlAlchemyEmitterRepository(session)
    document_repository = SqlAlchemyDocumentRepository(session)
    job_service = JobService(SqlAlchemyJobRepository(session))
    queue_adapter = None
    if settings.document_auto_enqueue and settings.encryption_key:
        queue = Queue(
            "documents",
            connection=Redis.from_url(settings.redis_url),
        )
        queue_adapter = RqJobQueue(queue)
    return DocumentService(
        document_repository=document_repository,
        emitter_repository=emitter_repository,
        job_service=job_service,
        queue=queue_adapter,
        database_url=settings.database_url,
        encryption_key=settings.encryption_key,
    )


def get_query_service(
    session: Session = Depends(get_db_session),
) -> QueryService:
    """Build the query application service for one request."""

    settings = get_settings()
    if not settings.encryption_key:
        raise RuntimeError("KILA_SIFEN_ENCRYPTION_KEY is required for queries.")

    return QueryService(
        emitter_repository=SqlAlchemyEmitterRepository(session),
        certificate_repository=SqlAlchemyCertificateRepository(session),
        document_repository=SqlAlchemyDocumentRepository(session),
        certificate_store=EncryptedCertificateStore(settings.encryption_key),
        query_gateway=PysifenQueryGateway(),
    )


def get_event_service(
    session: Session = Depends(get_db_session),
) -> EventService:
    """Build the event application service for one request."""

    settings = get_settings()
    if not settings.encryption_key:
        raise RuntimeError("KILA_SIFEN_ENCRYPTION_KEY is required for events.")

    return EventService(
        event_repository=SqlAlchemyEventRepository(session),
        emitter_repository=SqlAlchemyEmitterRepository(session),
        document_repository=SqlAlchemyDocumentRepository(session),
        certificate_repository=SqlAlchemyCertificateRepository(session),
        job_repository=SqlAlchemyJobRepository(session),
        certificate_store=EncryptedCertificateStore(settings.encryption_key),
        submission_gateway=PysifenEventGateway(),
    )


def get_webhook_service(
    session: Session = Depends(get_db_session),
) -> WebhookService:
    """Build the webhook application service for one request."""

    settings = get_settings()
    if not settings.encryption_key:
        raise RuntimeError("KILA_SIFEN_ENCRYPTION_KEY is required for webhooks.")

    queue = Queue(
        "webhooks",
        connection=Redis.from_url(settings.redis_url),
    )

    return WebhookService(
        webhook_repository=SqlAlchemyWebhookRepository(session),
        emitter_repository=SqlAlchemyEmitterRepository(session),
        job_repository=SqlAlchemyJobRepository(session),
        secret_store=EncryptedCertificateStore(settings.encryption_key),
        queue=RqJobQueue(queue),
        deliverer=WebhookDeliverer(),
        database_url=settings.database_url,
        encryption_key=settings.encryption_key,
    )


def get_admin_service(
    session: Session = Depends(get_db_session),
) -> AdminConsoleService:
    """Build the admin-console service for one request."""

    settings = get_settings()
    if not settings.encryption_key:
        raise RuntimeError("KILA_SIFEN_ENCRYPTION_KEY is required for admin.")

    redis_connection = Redis.from_url(settings.redis_url)
    document_queue = Queue("documents", connection=redis_connection)
    webhook_queue = Queue("webhooks", connection=redis_connection)

    emitter_repository = SqlAlchemyEmitterRepository(session)
    certificate_repository = SqlAlchemyCertificateRepository(session)
    stamping_repository = SqlAlchemyStampingRepository(session)
    document_repository = SqlAlchemyDocumentRepository(session)
    job_repository = SqlAlchemyJobRepository(session)
    webhook_repository = SqlAlchemyWebhookRepository(session)
    certificate_store = EncryptedCertificateStore(settings.encryption_key)
    certificate_service = CertificateService(
        certificate_repository=certificate_repository,
        emitter_repository=emitter_repository,
        certificate_store=certificate_store,
    )

    return AdminConsoleService(
        emitter_repository=emitter_repository,
        certificate_repository=certificate_repository,
        stamping_repository=stamping_repository,
        document_repository=document_repository,
        job_repository=job_repository,
        webhook_repository=webhook_repository,
        certificate_service=certificate_service,
        document_queue=RqJobQueue(document_queue),
        webhook_queue=RqJobQueue(webhook_queue),
        database_url=settings.database_url,
        encryption_key=settings.encryption_key,
    )
