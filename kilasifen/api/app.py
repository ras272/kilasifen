"""FastAPI application factory for Kila SIFEN."""

from fastapi import FastAPI

from kilasifen.api.routers.health import router as health_router
from kilasifen.config import get_settings
from kilasifen.logging import configure_logging


def create_app() -> FastAPI:
    """Create and configure the platform application."""

    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title=settings.api_title)
    app.include_router(health_router, prefix=f"/{settings.api_version}")
    return app
