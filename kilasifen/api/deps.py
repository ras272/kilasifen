"""Shared API dependencies."""

import hmac
import logging
from collections.abc import AsyncGenerator, Callable, Generator

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader
from redis import Redis
from sqlalchemy.orm import Session

from kilasifen.application.access.service import AccessService
from kilasifen.application.admin.service import AdminConsoleService
from kilasifen.application.certificates.service import CertificateService
from kilasifen.application.documents.numbering_service import DocumentNumberingService
from kilasifen.application.documents.service import DocumentService
from kilasifen.application.emitters.health import EmitterHealthService
from kilasifen.application.emitters.service import EmitterService
from kilasifen.application.events.service import EventService
from kilasifen.application.health.service import ReadinessService
from kilasifen.application.jobs.service import JobService
from kilasifen.application.queries.service import QueryService
from kilasifen.application.sandbox.service import SandboxOutcomePolicy
from kilasifen.application.stampings.service import StampingService
from kilasifen.application.webhooks.service import WebhookService
from kilasifen.config import get_settings
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.repositories.access import SqlAlchemyAccessRepository
from kilasifen.infrastructure.db.repositories.api_keys import SqlAlchemyApiKeyRepository
from kilasifen.infrastructure.db.repositories.certificates import (
    SqlAlchemyCertificateRepository,
)
from kilasifen.infrastructure.db.repositories.document_numbering_sequences import (
    SqlAlchemyDocumentNumberingSequenceRepository,
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
from kilasifen.infrastructure.db.session import session_scope
from kilasifen.infrastructure.jobs.outbox import SqlAlchemyJobOutboxQueue
from kilasifen.infrastructure.limits.redis import RedisRequestLimiter
from kilasifen.infrastructure.sifen.event import KilaSifenEventGateway
from kilasifen.infrastructure.sifen.query import KilaSifenQueryGateway
from kilasifen.infrastructure.sifen.raw_xml_policy import require_signable_raw_payload
from kilasifen.infrastructure.webhooks.deliverer import WebhookDeliverer
from kilasifen.infrastructure.webhooks.security import WebhookUrlPolicy
from kilasifen.security import (
    FISCAL_WRITE_SCOPE,
    PLATFORM_ADMIN_SCOPE,
    SECRETS_WRITE_SCOPE,
    TENANT_READ_SCOPE,
    TENANT_WRITE_SCOPE,
    ApiKeyPrincipal,
)

logger = logging.getLogger(__name__)
api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    scheme_name="KilaApiKey",
    description="Private consumer credential. Never expose it to browser clients.",
)


def get_api_key_principal(
    request: Request,
    x_api_key: str | None = Security(api_key_header),
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
        matched_position: int | None = None
        for position, bootstrap_key in enumerate(settings.api_keys):
            matched = hmac.compare_digest(x_api_key, bootstrap_key)
            if matched and matched_position is None:
                matched_position = position
        if matched_position is not None:
            repository.ensure_bootstrap_admin(
                settings.api_keys[matched_position],
                position=matched_position,
            )
        principal = repository.authenticate(
            x_api_key,
            bootstrap=matched_position is not None,
        )

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


async def enforce_request_limits(
    request: Request,
    principal: ApiKeyPrincipal = Depends(get_api_key_principal),
) -> AsyncGenerator[None, None]:
    """Acquire the global shared budget for one authenticated credential."""

    settings = get_settings()
    if settings.environment in {"development", "test"}:
        yield
        return

    redis = request.app.state.request_limit_redis
    limiter = RedisRequestLimiter(
        redis,
        requests_per_window=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
        max_concurrent=settings.max_concurrent_requests,
        lease_seconds=settings.request_lease_seconds,
    )
    identity = f"credential:{principal.consumer_id}:{principal.key_id}"
    lease = None
    try:
        try:
            lease = await limiter.acquire(identity)
        except Exception as exc:
            from kilasifen.api.errors import ApiError

            raise ApiError(
                status_code=503,
                code="limits.backend_unavailable",
                message="Request limiting is temporarily unavailable.",
                category="service_unavailable",
            ) from exc

        if not lease.acquired:
            from kilasifen.api.errors import ApiError

            raise ApiError(
                status_code=429,
                code=f"limits.{lease.reason}_exceeded",
                message="Request limit exceeded. Retry later.",
                category="rate_limit",
                details={"retry_after_seconds": lease.retry_after_seconds},
                headers={"Retry-After": str(lease.retry_after_seconds)},
            )
        yield
    finally:
        if lease is not None:
            try:
                await limiter.release(lease)
            except Exception:
                logger.exception("limits.lease_release_failed")


def get_db_session(request: Request) -> Generator[Session, None, None]:
    """Provide a database session for request handlers."""

    session_factory = request.app.state.session_factory
    with session_scope(session_factory) as session:
        yield session


def get_access_service(session: Session = Depends(get_db_session)) -> AccessService:
    """Build platform access administration use cases."""

    return AccessService(SqlAlchemyAccessRepository(session))


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
    secret_store = EncryptedCertificateStore(encryption_key) if encryption_key else None
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
        queue_adapter = _job_outbox_queue(session)
    return DocumentService(
        document_repository=document_repository,
        emitter_repository=emitter_repository,
        job_service=job_service,
        numbering_service=DocumentNumberingService(numbering_repository),
        queue=queue_adapter,
        database_url=settings.database_url,
        encryption_key=settings.encryption_key,
        sandbox_policy=SandboxOutcomePolicy(settings.environment),
        raw_payload_policy=require_signable_raw_payload,
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
        job_repository=SqlAlchemyJobRepository(session),
        certificate_store=EncryptedCertificateStore(settings.encryption_key),
        query_gateway=KilaSifenQueryGateway(settings.sifen_environment),
    )


def get_event_service(
    session: Session = Depends(get_db_session),
) -> EventService:
    """Build the event application service for one request."""

    settings = get_settings()
    if not settings.encryption_key:
        raise RuntimeError("KILA_SIFEN_ENCRYPTION_KEY is required for events.")

    outbox_queue = _job_outbox_queue(session)
    webhook_service = WebhookService(
        webhook_repository=SqlAlchemyWebhookRepository(session),
        emitter_repository=_emitter_repository(session),
        job_repository=SqlAlchemyJobRepository(session),
        secret_store=EncryptedCertificateStore(settings.encryption_key),
        queue=outbox_queue,
        deliverer=WebhookDeliverer(
            url_policy=WebhookUrlPolicy.for_environment(settings.environment)
        ),
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
        submission_gateway=KilaSifenEventGateway(settings.sifen_environment),
        inutilized_range_repository=SqlAlchemyInutilizedNumberRangeRepository(session),
        stamping_repository=SqlAlchemyStampingRepository(session),
        query_gateway=KilaSifenQueryGateway(settings.sifen_environment),
        webhook_publisher=webhook_service,
        queue=outbox_queue,
        database_url=settings.database_url,
        encryption_key=settings.encryption_key,
    )


def get_webhook_service(
    session: Session = Depends(get_db_session),
) -> WebhookService:
    """Build the webhook application service for one request."""

    settings = get_settings()
    if not settings.encryption_key:
        raise RuntimeError("KILA_SIFEN_ENCRYPTION_KEY is required for webhooks.")

    return WebhookService(
        webhook_repository=SqlAlchemyWebhookRepository(session),
        emitter_repository=_emitter_repository(session),
        job_repository=SqlAlchemyJobRepository(session),
        secret_store=EncryptedCertificateStore(settings.encryption_key),
        queue=_job_outbox_queue(session),
        deliverer=WebhookDeliverer(
            url_policy=WebhookUrlPolicy.for_environment(settings.environment)
        ),
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

    outbox_queue = _job_outbox_queue(session)

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
        document_queue=outbox_queue,
        event_queue=outbox_queue,
        webhook_queue=outbox_queue,
        database_url=settings.database_url,
        encryption_key=settings.encryption_key,
    )


def _job_outbox_queue(session: Session) -> SqlAlchemyJobOutboxQueue:
    return SqlAlchemyJobOutboxQueue(SqlAlchemyJobOutboxRepository(session))
