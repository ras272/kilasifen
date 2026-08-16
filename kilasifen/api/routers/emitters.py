"""Emitter API routes."""

from fastapi import APIRouter, Depends, Request, status

from kilasifen.api.deps import (
    get_api_key_principal,
    get_emitter_health_service,
    get_emitter_service,
)
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.api.schemas.emitters import (
    EmitterCreateRequest,
    EmitterHealthResponse,
    EmitterResponse,
    EmitterUpdateRequest,
)
from kilasifen.application.emitters.health import EmitterHealthService
from kilasifen.application.emitters.service import EmitterService
from kilasifen.domain.emitters.models import Emitter
from kilasifen.security import ApiKeyPrincipal, TENANT_READ_SCOPE, TENANT_WRITE_SCOPE

router = APIRouter(prefix="/emitters", tags=["emitters"])


@router.post("", response_model=SuccessEnvelope, status_code=status.HTTP_201_CREATED)
def create_emitter(
    payload: EmitterCreateRequest,
    request: Request,
    principal: ApiKeyPrincipal = Depends(get_api_key_principal),
    service: EmitterService = Depends(get_emitter_service),
) -> SuccessEnvelope:
    principal.require_scope(TENANT_WRITE_SCOPE)
    emitter = service.create_emitter(
        **payload.model_dump(), owner_consumer_id=principal.consumer_id
    )
    return _envelope(request, emitter)


@router.get("/{emitter_id}", response_model=SuccessEnvelope)
def get_emitter(
    emitter_id: str,
    request: Request,
    principal: ApiKeyPrincipal = Depends(get_api_key_principal),
    service: EmitterService = Depends(get_emitter_service),
) -> SuccessEnvelope:
    principal.require_scope(TENANT_READ_SCOPE)
    principal.require_emitter(emitter_id)
    emitter = service.get_emitter(emitter_id)
    return _envelope(request, emitter)


@router.patch("/{emitter_id}", response_model=SuccessEnvelope)
def update_emitter(
    emitter_id: str,
    payload: EmitterUpdateRequest,
    request: Request,
    principal: ApiKeyPrincipal = Depends(get_api_key_principal),
    service: EmitterService = Depends(get_emitter_service),
) -> SuccessEnvelope:
    principal.require_scope(TENANT_WRITE_SCOPE)
    principal.require_emitter(emitter_id)
    emitter = service.update_emitter(emitter_id, **payload.model_dump())
    return _envelope(request, emitter)


@router.post("/{emitter_id}/deactivate", response_model=SuccessEnvelope)
def deactivate_emitter(
    emitter_id: str,
    request: Request,
    principal: ApiKeyPrincipal = Depends(get_api_key_principal),
    service: EmitterService = Depends(get_emitter_service),
) -> SuccessEnvelope:
    principal.require_scope(TENANT_WRITE_SCOPE)
    principal.require_emitter(emitter_id)
    emitter = service.deactivate_emitter(emitter_id)
    return _envelope(request, emitter)


@router.get("/{emitter_id}/health", response_model=SuccessEnvelope)
def get_emitter_health(
    emitter_id: str,
    request: Request,
    principal: ApiKeyPrincipal = Depends(get_api_key_principal),
    service: EmitterHealthService = Depends(get_emitter_health_service),
) -> SuccessEnvelope:
    principal.require_scope(TENANT_READ_SCOPE)
    principal.require_emitter(emitter_id)
    health = service.get_health(emitter_id=emitter_id)
    return SuccessEnvelope(
        data={"health": EmitterHealthResponse.model_validate(health).model_dump(mode="json")},
        correlation_id=request.state.correlation_id,
    )


def _envelope(request: Request, emitter: Emitter) -> SuccessEnvelope:
    response = EmitterResponse(
        id=emitter.id,
        external_id=emitter.external_id,
        ruc=emitter.ruc,
        dv=emitter.dv,
        legal_name=emitter.legal_name,
        tax_environment=emitter.tax_environment,
        status=emitter.status,
        csc_configured=emitter.csc is not None,
        csc_id=emitter.csc_id,
        created_at=emitter.created_at,
        updated_at=emitter.updated_at,
    )
    return SuccessEnvelope(
        data={"emitter": response.model_dump(mode="json")},
        correlation_id=request.state.correlation_id,
    )
