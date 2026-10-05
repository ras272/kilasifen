"""Emitter API routes."""

from fastapi import APIRouter, Depends, Request, status

from kilasifen.api.deps import (
    get_admin_principal,
    get_api_key_principal,
    get_emitter_health_service,
    get_emitter_service,
)
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.api.schemas.emitters import (
    EmitterCreateRequest,
    EmitterFiscalProfileModel,
    EmitterHealthResponse,
    EmitterResponse,
    EmitterUpdateRequest,
)
from kilasifen.application.emitters.health import EmitterHealthService
from kilasifen.application.emitters.service import EmitterService
from kilasifen.domain.emitters.fiscal_profile import EmitterFiscalProfile
from kilasifen.domain.emitters.models import Emitter, EmitterSummary
from kilasifen.security import (
    SECRETS_WRITE_SCOPE,
    TENANT_READ_SCOPE,
    TENANT_WRITE_SCOPE,
    ApiKeyPrincipal,
)

router = APIRouter(prefix="/emitters", tags=["emitters"])


@router.post("", response_model=SuccessEnvelope, status_code=status.HTTP_201_CREATED)
def create_emitter(
    payload: EmitterCreateRequest,
    request: Request,
    principal: ApiKeyPrincipal = Depends(get_admin_principal),
    service: EmitterService = Depends(get_emitter_service),
) -> SuccessEnvelope:
    create_payload = payload.model_dump(
        exclude={"owner_consumer_id", "fiscal_profile"}
    )
    emitter = service.create_emitter(
        **create_payload,
        owner_consumer_id=payload.owner_consumer_id or principal.consumer_id,
        fiscal_profile=_profile_to_domain(payload.fiscal_profile),
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
    if payload.csc is not None or payload.csc_id is not None:
        principal.require_scope(SECRETS_WRITE_SCOPE)
    emitter = service.update_emitter(
        emitter_id,
        **payload.model_dump(exclude={"fiscal_profile"}),
        fiscal_profile=_profile_to_domain(payload.fiscal_profile),
    )
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
        data={
            "health": EmitterHealthResponse.model_validate(health).model_dump(
                mode="json"
            )
        },
        correlation_id=request.state.correlation_id,
    )


def _profile_to_domain(
    profile: EmitterFiscalProfileModel | None,
) -> EmitterFiscalProfile | None:
    return profile.to_domain() if profile is not None else None


def _envelope(
    request: Request,
    emitter: Emitter | EmitterSummary,
) -> SuccessEnvelope:
    csc_configured = (
        emitter.csc_configured
        if isinstance(emitter, EmitterSummary)
        else emitter.csc is not None
    )
    response = EmitterResponse(
        id=emitter.id,
        external_id=emitter.external_id,
        ruc=emitter.ruc,
        dv=emitter.dv,
        legal_name=emitter.legal_name,
        tax_environment=emitter.tax_environment,
        status=emitter.status,
        csc_configured=csc_configured,
        csc_id=emitter.csc_id,
        fiscal_profile=(
            EmitterFiscalProfileModel.from_domain(emitter.fiscal_profile)
            if emitter.fiscal_profile is not None
            else None
        ),
        fiscal_profile_complete=emitter.fiscal_profile is not None,
        created_at=emitter.created_at,
        updated_at=emitter.updated_at,
    )
    return SuccessEnvelope(
        data={"emitter": response.model_dump(mode="json")},
        correlation_id=request.state.correlation_id,
    )
