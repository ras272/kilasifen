"""Healthcheck routes."""

from fastapi import APIRouter, Request

from kilasifen.api.schemas.common import SuccessEnvelope

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> SuccessEnvelope:
    """Return the liveness status."""

    return SuccessEnvelope(
        data={"status": "ok"},
        correlation_id=request.state.correlation_id,
    )


@router.get("/ready")
def ready(request: Request) -> SuccessEnvelope:
    """Return the readiness status."""

    return SuccessEnvelope(
        data={"status": "ready"},
        correlation_id=request.state.correlation_id,
    )
