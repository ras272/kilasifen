"""Emitter API routes."""

from fastapi import APIRouter, Depends, Query, Request, status

from kilasifen.api.deps import (
    get_emitter_health_service,
    get_emitter_service,
    require_emitter_create,
    require_emitter_read,
    require_emitter_write,
    require_tenant_read,
)
from kilasifen.api.errors import ApiError
from kilasifen.api.schemas.emitters import (
    EmitterCreateRequest,
    EmitterData,
    EmitterEnvelope,
    EmitterFiscalProfileModel,
    EmitterHealthData,
    EmitterHealthEnvelope,
    EmitterHealthResponse,
    EmitterListData,
    EmitterListEnvelope,
    EmitterResponse,
    EmitterUpdateRequest,
)
from kilasifen.application.emitters.health import EmitterHealthService
from kilasifen.application.emitters.service import EmitterService
from kilasifen.domain.emitters.fiscal_profile import EmitterFiscalProfile
from kilasifen.domain.emitters.models import Emitter, EmitterSummary
from kilasifen.security import SECRETS_WRITE_SCOPE, ApiKeyPrincipal

router = APIRouter(prefix="/emitters", tags=["emitters"])


@router.post(
    "",
    response_model=EmitterEnvelope,
    status_code=status.HTTP_201_CREATED,
    description=(
        "Da de alta un emisor (un RUC). Con `emitters:create` el emisor queda "
        "siempre a nombre del consumidor de la credencial: es el alta "
        "autoservicio de los clientes de un ERP. Con `platform:admin` puede "
        "asignarse a cualquier consumidor con `owner_consumer_id`. RUC+DV y "
        "`external_id` son únicos en la plataforma (`409`); si se pierde la "
        "respuesta, el emisor se recupera con `GET /v1/emitters?external_id=`."
    ),
)
def create_emitter(
    payload: EmitterCreateRequest,
    request: Request,
    principal: ApiKeyPrincipal = Depends(require_emitter_create),
    service: EmitterService = Depends(get_emitter_service),
) -> EmitterEnvelope:
    create_payload = payload.model_dump(
        exclude={"owner_consumer_id", "fiscal_profile"}
    )
    emitter = service.create_emitter(
        **create_payload,
        owner_consumer_id=_owner_for(principal, payload.owner_consumer_id),
        fiscal_profile=_profile_to_domain(payload.fiscal_profile),
    )
    return _envelope(request, emitter)


@router.get(
    "",
    response_model=EmitterListEnvelope,
    description=(
        "Emisores del consumidor de la credencial, del más nuevo al más viejo "
        "(con `platform:admin`, todos). `external_id` y `ruc` (con o sin DV) "
        "filtran; sirven para recuperar el `emitter_id` de un alta cuya "
        "respuesta se perdió."
    ),
)
def list_emitters(
    request: Request,
    external_id: str | None = Query(default=None, min_length=1, max_length=128),
    ruc: str | None = Query(default=None, min_length=3, max_length=10),
    limit: int = Query(default=50, ge=1, le=200),
    principal: ApiKeyPrincipal = Depends(require_tenant_read),
    service: EmitterService = Depends(get_emitter_service),
) -> EmitterListEnvelope:
    emitters = service.list_emitters(
        owner_consumer_id=(
            None if principal.is_platform_admin else principal.consumer_id
        ),
        external_id=external_id,
        ruc=ruc,
        limit=limit,
    )
    return EmitterListEnvelope(
        data=EmitterListData(emitters=[_response(emitter) for emitter in emitters]),
        correlation_id=request.state.correlation_id,
    )


@router.get("/{emitter_id}", response_model=EmitterEnvelope)
def get_emitter(
    emitter_id: str,
    request: Request,
    _principal=Depends(require_emitter_read),
    service: EmitterService = Depends(get_emitter_service),
) -> EmitterEnvelope:
    emitter = service.get_emitter(emitter_id)
    return _envelope(request, emitter)


@router.patch(
    "/{emitter_id}",
    response_model=EmitterEnvelope,
    description="Cambiar `csc` o `csc_id` exige además el scope `secrets:write`.",
)
def update_emitter(
    emitter_id: str,
    payload: EmitterUpdateRequest,
    request: Request,
    principal: ApiKeyPrincipal = Depends(require_emitter_write),
    service: EmitterService = Depends(get_emitter_service),
) -> EmitterEnvelope:
    if payload.csc is not None or payload.csc_id is not None:
        principal.require_scope(SECRETS_WRITE_SCOPE)
    emitter = service.update_emitter(
        emitter_id,
        **payload.model_dump(exclude={"fiscal_profile"}),
        fiscal_profile=_profile_to_domain(payload.fiscal_profile),
    )
    return _envelope(request, emitter)


@router.post("/{emitter_id}/deactivate", response_model=EmitterEnvelope)
def deactivate_emitter(
    emitter_id: str,
    request: Request,
    _principal=Depends(require_emitter_write),
    service: EmitterService = Depends(get_emitter_service),
) -> EmitterEnvelope:
    emitter = service.deactivate_emitter(emitter_id)
    return _envelope(request, emitter)


@router.get(
    "/{emitter_id}/health",
    response_model=EmitterHealthEnvelope,
)
def get_emitter_health(
    emitter_id: str,
    request: Request,
    _principal=Depends(require_emitter_read),
    service: EmitterHealthService = Depends(get_emitter_health_service),
) -> EmitterHealthEnvelope:
    health = service.get_health(emitter_id=emitter_id)
    return EmitterHealthEnvelope(
        data=EmitterHealthData(health=EmitterHealthResponse.model_validate(health)),
        correlation_id=request.state.correlation_id,
    )


def _profile_to_domain(
    profile: EmitterFiscalProfileModel | None,
) -> EmitterFiscalProfile | None:
    return profile.to_domain() if profile is not None else None


def _owner_for(principal: ApiKeyPrincipal, requested: str | None) -> str:
    """Consumer that owns a new emitter.

    A platform administrator may assign it to any consumer; any other
    credential creates emitters for its own consumer only.
    """

    if principal.is_platform_admin:
        return requested or principal.consumer_id
    if requested is not None and requested != principal.consumer_id:
        raise ApiError(
            status_code=403,
            code="emitters.owner_not_allowed",
            message="Emitters can only be created for the credential's own consumer.",
            category="authorization",
        )
    return principal.consumer_id


def _envelope(
    request: Request,
    emitter: Emitter | EmitterSummary,
) -> EmitterEnvelope:
    return EmitterEnvelope(
        data=EmitterData(emitter=_response(emitter)),
        correlation_id=request.state.correlation_id,
    )


def _response(emitter: Emitter | EmitterSummary) -> EmitterResponse:
    csc_configured = (
        emitter.csc_configured
        if isinstance(emitter, EmitterSummary)
        else emitter.csc is not None
    )
    return EmitterResponse(
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
