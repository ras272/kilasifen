"""Liveness and dependency-aware readiness routes."""

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from kilasifen.api.deps import get_readiness_service
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.api.schemas.health import DependencyCheckResponse, ReadinessData
from kilasifen.application.health.service import ReadinessService

router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> SuccessEnvelope:
    """Return the liveness status."""

    return SuccessEnvelope(
        data={"status": "ok"},
        correlation_id=request.state.correlation_id,
    )


@router.get(
    "/ready",
    response_model=SuccessEnvelope,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": SuccessEnvelope}},
)
def ready(
    request: Request,
    service: ReadinessService = Depends(get_readiness_service),
) -> SuccessEnvelope | JSONResponse:
    """Report whether mandatory storage, queue, and worker dependencies are usable."""

    report = service.check()
    readiness = ReadinessData(
        status="ready" if report.is_ready else "not_ready",
        checks={
            "database": DependencyCheckResponse(
                status=report.database.status,
                detail=report.database.detail,
            ),
            "redis": DependencyCheckResponse(
                status=report.redis.status,
                detail=report.redis.detail,
            ),
            "workers": DependencyCheckResponse(
                status=report.workers.status,
                detail=report.workers.detail,
            ),
        },
    )
    envelope = SuccessEnvelope(
        data=readiness.model_dump(exclude_none=True),
        correlation_id=request.state.correlation_id,
    )
    if report.is_ready:
        return envelope
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=envelope.model_dump(),
    )
