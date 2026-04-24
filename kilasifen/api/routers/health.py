"""Healthcheck routes."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Return the liveness status."""

    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict[str, str]:
    """Return the readiness status."""

    return {"status": "ready"}
