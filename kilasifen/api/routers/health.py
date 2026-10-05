"""Liveness and dependency-aware readiness routes."""

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from kilasifen.api.deps import get_readiness_service
from kilasifen.api.schemas.health import (
    DependencyCheckResponse,
    HealthData,
    HealthEnvelope,
    ReadinessData,
    ReadinessEnvelope,
)
from kilasifen.application.health.service import ReadinessService

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthEnvelope)
def health(request: Request) -> HealthEnvelope:
    """Responde `ok` mientras el proceso de la API atiende pedidos."""

    return HealthEnvelope(
        data=HealthData(status="ok"),
        correlation_id=request.state.correlation_id,
    )


@router.get(
    "/ready",
    response_model=ReadinessEnvelope,
    response_model_exclude_none=True,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ReadinessEnvelope,
            "description": (
                "Alguna dependencia obligatoria no está disponible: el detalle "
                "va en `data.checks`, no en un `ErrorEnvelope`."
            ),
        }
    },
)
def ready(
    request: Request,
    service: ReadinessService = Depends(get_readiness_service),
) -> ReadinessEnvelope | JSONResponse:
    """Indica si la base, Redis y los workers obligatorios están disponibles."""

    report = request.app.state.readiness_probe_cache.get_or_check(service.check)
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
    envelope = ReadinessEnvelope(
        data=readiness,
        correlation_id=request.state.correlation_id,
    )
    if report.is_ready:
        return envelope
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=envelope.model_dump(mode="json", exclude_none=True),
    )
