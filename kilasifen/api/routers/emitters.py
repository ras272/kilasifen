"""Emitter API routes."""

from fastapi import APIRouter, Depends, Request, status

from kilasifen.api.deps import get_api_key_principal, get_emitter_service
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.api.schemas.emitters import (
    EmitterCreateRequest,
    EmitterResponse,
    EmitterUpdateRequest,
)
from kilasifen.application.emitters.service import EmitterService
from kilasifen.domain.emitters.models import Emitter

router = APIRouter(prefix="/emitters", tags=["emitters"])


@router.post("", response_model=SuccessEnvelope, status_code=status.HTTP_201_CREATED)
def create_emitter(
    payload: EmitterCreateRequest,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: EmitterService = Depends(get_emitter_service),
) -> SuccessEnvelope:
    emitter = service.create_emitter(**payload.model_dump())
    return _envelope(request, emitter)


@router.get("/{emitter_id}", response_model=SuccessEnvelope)
def get_emitter(
    emitter_id: str,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: EmitterService = Depends(get_emitter_service),
) -> SuccessEnvelope:
    emitter = service.get_emitter(emitter_id)
    return _envelope(request, emitter)


@router.patch("/{emitter_id}", response_model=SuccessEnvelope)
def update_emitter(
    emitter_id: str,
    payload: EmitterUpdateRequest,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: EmitterService = Depends(get_emitter_service),
) -> SuccessEnvelope:
    emitter = service.update_emitter(emitter_id, **payload.model_dump())
    return _envelope(request, emitter)


@router.post("/{emitter_id}/deactivate", response_model=SuccessEnvelope)
def deactivate_emitter(
    emitter_id: str,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: EmitterService = Depends(get_emitter_service),
) -> SuccessEnvelope:
    emitter = service.deactivate_emitter(emitter_id)
    return _envelope(request, emitter)


def _envelope(request: Request, emitter: Emitter) -> SuccessEnvelope:
    return SuccessEnvelope(
        data={"emitter": EmitterResponse.model_validate(emitter).model_dump(mode="json")},
        correlation_id=request.state.correlation_id,
    )
