"""FastAPI application factory for Kila SIFEN."""

import logging
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, FastAPI, Request

from kilasifen.admin.router import router as admin_router
from kilasifen.api.deps import get_api_key_principal
from kilasifen.api.errors import (
    ApiError,
    api_error_handler,
    conflict_error_handler,
    not_found_error_handler,
    service_unavailable_error_handler,
    unprocessable_entity_error_handler,
)
from kilasifen.api.routers.certificates import router as certificates_router
from kilasifen.api.routers.documents import router as documents_router
from kilasifen.api.routers.emitters import router as emitters_router
from kilasifen.api.routers.events import router as events_router
from kilasifen.api.routers.health import router as health_router
from kilasifen.api.routers.jobs import router as jobs_router
from kilasifen.api.routers.queries import router as queries_router
from kilasifen.api.routers.stampings import router as stampings_router
from kilasifen.api.routers.webhooks import router as webhooks_router
from kilasifen.api.schemas.common import SuccessEnvelope
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

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the platform application."""

    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title=settings.api_title)
    engine = build_engine(settings.database_url)
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(NotFoundError, not_found_error_handler)
    app.add_exception_handler(ConflictError, conflict_error_handler)
    app.add_exception_handler(
        UnprocessableEntityError, unprocessable_entity_error_handler
    )
    app.add_exception_handler(
        ServiceUnavailableError, service_unavailable_error_handler
    )

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

        response.headers["X-Correlation-ID"] = correlation_id
        return response

    app.include_router(health_router, prefix=f"/{settings.api_version}")
    app.include_router(emitters_router, prefix=f"/{settings.api_version}")
    app.include_router(certificates_router, prefix=f"/{settings.api_version}")
    app.include_router(stampings_router, prefix=f"/{settings.api_version}")
    app.include_router(documents_router, prefix=f"/{settings.api_version}")
    app.include_router(jobs_router, prefix=f"/{settings.api_version}")
    app.include_router(queries_router, prefix=f"/{settings.api_version}")
    app.include_router(events_router, prefix=f"/{settings.api_version}")
    app.include_router(webhooks_router, prefix=f"/{settings.api_version}")
    app.include_router(admin_router)

    @app.get(
        f"/{settings.api_version}/auth/check",
        response_model=SuccessEnvelope,
        tags=["auth"],
    )
    def auth_check(
        request: Request,
        _principal=Depends(get_api_key_principal),
    ) -> SuccessEnvelope:
        return SuccessEnvelope(
            data={"authenticated": True},
            correlation_id=request.state.correlation_id,
        )

    return app
