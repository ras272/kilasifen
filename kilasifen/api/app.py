"""FastAPI application factory for Kila SIFEN."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from redis.asyncio import Redis as AsyncRedis
from starlette.exceptions import HTTPException as StarletteHTTPException

from kilasifen.admin.router import router as admin_router
from kilasifen.api.deps import enforce_request_limits
from kilasifen.api.errors import (
    CORRELATION_ID_HEADER,
    ApiError,
    api_error_handler,
    conflict_error_handler,
    error_responses,
    http_exception_handler,
    not_found_error_handler,
    request_validation_error_handler,
    service_unavailable_error_handler,
    unhandled_error_handler,
    unprocessable_entity_error_handler,
)
from kilasifen.api.middleware import (
    PreAuthRateLimitMiddleware,
    RequestBodyLimitMiddleware,
)
from kilasifen.api.openapi import install_openapi_extensions
from kilasifen.api.routers.access import router as access_router
from kilasifen.api.routers.auth import router as auth_router
from kilasifen.api.routers.certificates import router as certificates_router
from kilasifen.api.routers.documents import router as documents_router
from kilasifen.api.routers.emitters import router as emitters_router
from kilasifen.api.routers.events import router as events_router
from kilasifen.api.routers.health import router as health_router
from kilasifen.api.routers.jobs import router as jobs_router
from kilasifen.api.routers.queries import router as queries_router
from kilasifen.api.routers.stampings import router as stampings_router
from kilasifen.api.routers.webhooks import router as webhooks_router
from kilasifen.application.health.service import ReadinessProbeCache
from kilasifen.config import get_settings
from kilasifen.domain.common.errors import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    UnprocessableEntityError,
)
from kilasifen.infrastructure.db.session import build_engine, build_session_factory
from kilasifen.logging import (
    configure_logging,
    reset_correlation_id,
    set_correlation_id,
)
from kilasifen.observability import initialize_sentry

logger = logging.getLogger(__name__)

# Error envelopes declared in the OpenAPI contract for authenticated routers.
# Every protected route authenticates (401), checks a scope (403), resolves an
# owned emitter or resource (404), validates input (422) and goes through the
# shared request limiter (429, or 503 when its backend is unavailable). Routers
# with write routes also declare 409 and the body size limit (413).
_READ_ONLY_ERROR_RESPONSES = error_responses(401, 403, 404, 422, 429, 503)
_TENANT_ERROR_RESPONSES = error_responses(401, 403, 404, 409, 413, 422, 429, 503)
_PROTECTED_ROUTERS: tuple[tuple[APIRouter, dict], ...] = (
    (emitters_router, _TENANT_ERROR_RESPONSES),
    (certificates_router, _TENANT_ERROR_RESPONSES),
    (stampings_router, _TENANT_ERROR_RESPONSES),
    (documents_router, _TENANT_ERROR_RESPONSES),
    (jobs_router, _READ_ONLY_ERROR_RESPONSES),
    (queries_router, _TENANT_ERROR_RESPONSES),
    (events_router, _TENANT_ERROR_RESPONSES),
    (webhooks_router, _TENANT_ERROR_RESPONSES),
    (access_router, _TENANT_ERROR_RESPONSES),
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Release process-local resources during graceful shutdown."""

    try:
        yield
    finally:
        try:
            await app.state.request_limit_redis.aclose()
        except Exception:
            logger.exception("limits.shared_redis_close_failed")
        finally:
            app.state.engine.dispose()


def create_app() -> FastAPI:
    """Create and configure the platform application."""

    settings = get_settings()
    configure_logging(settings.log_level)
    initialize_sentry(settings=settings, component="api")

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description=(
            "API fiscal multi-tenant para emitir, consultar y conciliar documentos "
            "electrónicos con SIFEN."
        ),
        lifespan=_lifespan,
    )
    engine = build_engine(settings.database_url)
    request_limit_redis = AsyncRedis.from_url(
        settings.redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.request_limit_redis = request_limit_redis
    app.state.readiness_probe_cache = ReadinessProbeCache(
        settings.readiness_cache_seconds
    )
    app.add_middleware(RequestBodyLimitMiddleware, settings=settings)
    app.add_middleware(
        PreAuthRateLimitMiddleware,
        settings=settings,
        redis=request_limit_redis,
    )
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(NotFoundError, not_found_error_handler)
    app.add_exception_handler(ConflictError, conflict_error_handler)
    app.add_exception_handler(
        UnprocessableEntityError, unprocessable_entity_error_handler
    )
    app.add_exception_handler(
        ServiceUnavailableError, service_unavailable_error_handler
    )
    app.add_exception_handler(
        RequestValidationError, request_validation_error_handler
    )
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    @app.middleware("http")
    async def add_correlation_id(request: Request, call_next):
        correlation_id = str(uuid4())
        token = set_correlation_id(correlation_id)
        request.state.correlation_id = correlation_id
        started_at = perf_counter()
        try:
            response = await call_next(request)
        finally:
            duration_ms = round((perf_counter() - started_at) * 1000, 2)
            route = request.scope.get("route")
            logger.info(
                "http.request.completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "route": getattr(route, "path", request.url.path),
                    "status_code": getattr(
                        locals().get("response"), "status_code", 500
                    ),
                    "duration_ms": duration_ms,
                    "emitter_id": request.path_params.get("emitter_id"),
                },
            )
            reset_correlation_id(token)

        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response

    api_prefix = f"/{settings.api_version}"
    app.include_router(health_router, prefix=api_prefix)
    limited = [Depends(enforce_request_limits)]
    for router, responses in _PROTECTED_ROUTERS:
        app.include_router(
            router,
            prefix=api_prefix,
            dependencies=limited,
            responses=responses,
        )
    app.include_router(admin_router, dependencies=limited)
    app.include_router(auth_router, prefix=api_prefix)

    install_openapi_extensions(
        app,
        api_prefix=api_prefix,
        routers=[
            health_router,
            auth_router,
            *(router for router, _responses in _PROTECTED_ROUTERS),
        ],
    )
    return app
