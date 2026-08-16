"""Shared API dependencies."""

from collections.abc import Callable, Generator
import hmac

from fastapi import Depends, Header, Request
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from kilasifen.application.admin.service import AdminConsoleService
from kilasifen.application.documents.numbering_service import DocumentNumberingService
from kilasifen.application.documents.service import DocumentService
from kilasifen.application.emitters.health import EmitterHealthService
from kilasifen.application.events.service import EventService
from kilasifen.application.health.service import ReadinessService
from kilasifen.application.jobs.service import JobService
from kilasifen.application.queries.service import QueryService
from kilasifen.application.stampings.service import StampingService
from kilasifen.application.webhooks.service import WebhookService
from kilasifen.application.certificates.service import CertificateService
from kilasifen.application.emitters.service import EmitterService
from kilasifen.config import get_settings
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.repositories.api_keys import SqlAlchemyApiKeyRepository
from kilasifen.infrastructure.db.repositories.documents import SqlAlchemyDocumentRepository
from kilasifen.infrastructure.db.repositories.document_numbering_sequences import (
    SqlAlchemyDocumentNumberingSequenceRepository,
)
from kilasifen.infrastructure.db.repositories.events import SqlAlchemyEventRepository
from kilasifen.infrastructure.db.repositories.inutilized_number_ranges import (
    SqlAlchemyInutilizedNumberRangeRepository,
)
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
from kilasifen.security import (
    ApiKeyPrincipal,
    FISCAL_WRITE_SCOPE,
    PLATFORM_ADMIN_SCOPE,
    SECRETS_WRITE_SCOPE,
    TENANT_READ_SCOPE,
    TENANT_WRITE_SCOPE,
)


def get_api_key_principal(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> ApiKeyPrincipal:
    """Resolve a hashed database credential into a non-secret principal."""

    if x_api_key is None:
        from kilasifen.api.errors import ApiError

        raise ApiError(
            status_code=401,
            code="auth.missing_api_key",
            message="API key is required.",
            category="authentication",
        )

    settings = get_settings()
    with session_scope(request.app.state.session_factory) as session:
        repository = SqlAlchemyApiKeyRepository(session)
        for position, bootstrap_key in enumerate(settings.api_keys):
            if hmac.compare_digest(x_api_key, bootstrap_key):
                repository.ensure_bootstrap_admin(bootstrap_key, position=position)
                break
        principal = repository.authenticate(x_api_key)

    if principal is None:
        from kilasifen.api.errors import ApiError

        raise ApiError(
            status_code=401,
            code="auth.invalid_api_key",
            message="API key is invalid.",
            category="authentication",
        )
    return principal


def get_admin_principal(
    principal: ApiKeyPrincipal = Depends(get_api_key_principal),
) -> ApiKeyPrincipal:
    """Require the distinct platform-administrator scope."""

    principal.require_scope(PLATFORM_ADMIN_SCOPE)
    return principal


def require_emitter_read(
    emitter_id: str,
    principal: ApiKeyPrincipal = Depends(get_api_key_principal),
) -> ApiKeyPrincipal:
    principal.require_scope(TENANT_READ_SCOPE)
    principal.require_emitter(emitter_id)
    return principal


def require_emitter_write(
    emitter_id: str,
    principal: ApiKeyPrincipal = Depends(get_api_key_principal),
) -> ApiKeyPrincipal:
    principal.require_scope(TENANT_WRITE_SCOPE)
    principal.require_emitter(emitter_id)
    return principal


def require_fiscal_write(
    emitter_id: str,
    principal: ApiKeyPrincipal = Depends(get_api_key_principal),
) -> ApiKeyPrincipal:
    principal.require_scope(FISCAL_WRITE_SCOPE)
    principal.require_emitter(emitter_id)
    return principal


def require_secrets_write(
    emitter_id: str,
    principal: ApiKeyPrincipal = Depends(get_api_key_principal),
) -> ApiKeyPrincipal:
    principal.require_scope(SECRETS_WRITE_SCOPE)
    principal.require_emitter(emitter_id)
    return principal


RequireApiKey = Callable[..., ApiKeyPrincipal]


def get_db_session(request: Request) -> Generator[Session, None, None]:
    """Provide a database session for request handlers."""

    session_factory = request.app.state.session_factory
    with session_scope(session_factory) as session:
        yield session


def get_readiness_service(request: Request) -> ReadinessService:
    """Build dependency probes with bounded Redis network timeouts."""

    settings = get_settings()
    redis_connection = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    return ReadinessService(
        engine=request.app.state.engine,
        redis_connection=redis_connection,
        require_workers=settings.readiness_requires_workers,
    )


def _emitter_repository(session: Session) -> SqlAlchemyEmitterRepository:
    encryption_key = get_settings().encryption_key
    secret_store = (
        EncryptedCertificateStore(encryption_key) if encryption_key else None
    )
    return SqlAlchemyEmitterRepository(session, secret_store)


def get_emitter_service(session: Session = Depends(get_db_session)) -> EmitterService:
    """Build the emitter application service for one request."""

    repository = _emitter_repository(session)
    return EmitterService(
        repository,
        deployment_tax_environment=get_settings().sifen_environment,
    )


def get_emitter_health_service(
    session: Session = Depends(get_db_session),
) -> EmitterHealthService:
    """Build the emitter-health service for one request."""

    return EmitterHealthService(
        emitter_repository=_emitter_repository(session),
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

    emitter_repository = _emitter_repository(session)
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

    emitter_repository = _emitter_repository(session)
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
    emitter_repository = _emitter_repository(session)
    document_repository = SqlAlchemyDocumentRepository(session)
    numbering_repository = SqlAlchemyDocumentNumberingSequenceRepository(session)
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
        numbering_service=DocumentNumberingService(numbering_repository),
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
        emitter_repository=_emitter_repository(session),
        certificate_repository=SqlAlchemyCertificateRepository(session),
        document_repository=SqlAlchemyDocumentRepository(session),
        certificate_store=EncryptedCertificateStore(settings.encryption_key),
        query_gateway=PysifenQueryGateway(settings.sifen_environment),
    )


def get_event_service(
    session: Session = Depends(get_db_session),
) -> EventService:
    """Build the event application service for one request."""

    settings = get_settings()
    if not settings.encryption_key:
        raise RuntimeError("KILA_SIFEN_ENCRYPTION_KEY is required for events.")

    webhook_queue = Queue(
        "webhooks",
        connection=Redis.from_url(settings.redis_url),
    )
    webhook_service = WebhookService(
        webhook_repository=SqlAlchemyWebhookRepository(session),
        emitter_repository=_emitter_repository(session),
        job_repository=SqlAlchemyJobRepository(session),
        secret_store=EncryptedCertificateStore(settings.encryption_key),
        queue=RqJobQueue(webhook_queue),
        deliverer=WebhookDeliverer(),
        database_url=settings.database_url,
        encryption_key=settings.encryption_key,
    )

    return EventService(
        event_repository=SqlAlchemyEventRepository(session),
        emitter_repository=_emitter_repository(session),
        document_repository=SqlAlchemyDocumentRepository(session),
        certificate_repository=SqlAlchemyCertificateRepository(session),
        job_repository=SqlAlchemyJobRepository(session),
        certificate_store=EncryptedCertificateStore(settings.encryption_key),
        submission_gateway=PysifenEventGateway(settings.sifen_environment),
        numbering_repository=SqlAlchemyDocumentNumberingSequenceRepository(session),
        inutilized_range_repository=SqlAlchemyInutilizedNumberRangeRepository(session),
        webhook_publisher=webhook_service,
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
        emitter_repository=_emitter_repository(session),
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

    emitter_repository = _emitter_repository(session)
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
