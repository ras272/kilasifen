"""FastAPI application factory for Kila SIFEN."""

from uuid import uuid4

from fastapi import Depends, FastAPI, Request

from kilasifen.api.routers.health import router as health_router
from kilasifen.api.deps import get_api_key_principal
from kilasifen.api.errors import ApiError, api_error_handler
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.config import get_settings
from kilasifen.logging import configure_logging


def create_app() -> FastAPI:
    """Create and configure the platform application."""

    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title=settings.api_title)
    app.add_exception_handler(ApiError, api_error_handler)

    @app.middleware("http")
    async def add_correlation_id(request: Request, call_next):
        request.state.correlation_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        return response

    app.include_router(health_router, prefix=f"/{settings.api_version}")

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
