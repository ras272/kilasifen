"""Stamping API routes."""

from fastapi import APIRouter, Depends, Request, status

from kilasifen.api.deps import (
    get_stamping_service,
    require_emitter_read,
    require_fiscal_write,
)
from kilasifen.api.schemas.stampings import (
    StampingCreateRequest,
    StampingData,
    StampingEnvelope,
    StampingListData,
    StampingListEnvelope,
    StampingResponse,
)
from kilasifen.application.stampings.service import StampingService
from kilasifen.domain.stampings.models import Stamping

router = APIRouter(tags=["stampings"])


@router.post(
    "/emitters/{emitter_id}/stampings",
    response_model=StampingEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def create_stamping(
    emitter_id: str,
    payload: StampingCreateRequest,
    request: Request,
    _principal=Depends(require_fiscal_write),
    service: StampingService = Depends(get_stamping_service),
) -> StampingEnvelope:
    stamping = service.create_stamping(emitter_id=emitter_id, **payload.model_dump())
    return _stamping_envelope(request, stamping)


@router.get(
    "/emitters/{emitter_id}/stampings",
    response_model=StampingListEnvelope,
)
def list_stampings(
    emitter_id: str,
    request: Request,
    _principal=Depends(require_emitter_read),
    service: StampingService = Depends(get_stamping_service),
) -> StampingListEnvelope:
    stampings = service.list_stampings(emitter_id)
    return StampingListEnvelope(
        data=StampingListData(
            stampings=[
                StampingResponse.model_validate(stamping) for stamping in stampings
            ]
        ),
        correlation_id=request.state.correlation_id,
    )


@router.post(
    "/emitters/{emitter_id}/stampings/{stamping_id}/activate",
    response_model=StampingEnvelope,
)
def activate_stamping(
    emitter_id: str,
    stamping_id: str,
    request: Request,
    _principal=Depends(require_fiscal_write),
    service: StampingService = Depends(get_stamping_service),
) -> StampingEnvelope:
    stamping = service.activate_stamping_for_emitter(
        emitter_id=emitter_id,
        stamping_id=stamping_id,
    )
    return _stamping_envelope(request, stamping)


def _stamping_envelope(
    request: Request, stamping: Stamping
) -> StampingEnvelope:
    return StampingEnvelope(
        data=StampingData(stamping=StampingResponse.model_validate(stamping)),
        correlation_id=request.state.correlation_id,
    )
