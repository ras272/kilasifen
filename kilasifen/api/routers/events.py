"""Event API routes."""

from fastapi import APIRouter, Depends, Request, status

from kilasifen.api.deps import get_api_key_principal, get_event_service
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.api.schemas.events import EventCreateRequest, EventResponse
from kilasifen.api.schemas.jobs import JobResponse
from kilasifen.application.events.service import EventService

router = APIRouter(tags=["events"])


@router.post(
    "/emitters/{emitter_id}/events",
    response_model=SuccessEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def create_event(
    emitter_id: str,
    payload: EventCreateRequest,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: EventService = Depends(get_event_service),
) -> SuccessEnvelope:
    event, job = service.create_event(
        emitter_id=emitter_id,
        document_id=payload.document_id,
        event_type=payload.event_type,
        input_payload=payload.payload,
    )
    return SuccessEnvelope(
        data={
            "event": EventResponse.model_validate(event).model_dump(mode="json"),
            "job": JobResponse.model_validate(job).model_dump(mode="json"),
        },
        correlation_id=request.state.correlation_id,
    )


@router.get("/events/{event_id}", response_model=SuccessEnvelope)
def get_event(
    event_id: str,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: EventService = Depends(get_event_service),
) -> SuccessEnvelope:
    event, job = service.get_event(event_id)
    return SuccessEnvelope(
        data={
            "event": EventResponse.model_validate(event).model_dump(mode="json"),
            "job": JobResponse.model_validate(job).model_dump(mode="json") if job else None,
        },
        correlation_id=request.state.correlation_id,
    )
