"""Event API routes."""

from fastapi import APIRouter, Depends, Request, status

from kilasifen.api.deps import get_event_service, require_emitter_read, require_fiscal_write
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.api.schemas.events import (
    CancelDocumentRequest,
    EventCreateRequest,
    EventResponse,
    InutilizedRangeResponse,
    InutilizeRequest,
)
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
    _principal=Depends(require_emitter_read),
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


@router.post(
    "/emitters/{emitter_id}/documents/{document_id}/cancel",
    response_model=SuccessEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def cancel_document(
    emitter_id: str,
    document_id: str,
    payload: CancelDocumentRequest,
    request: Request,
    _principal=Depends(require_fiscal_write),
    service: EventService = Depends(get_event_service),
) -> SuccessEnvelope:
    event, job = service.cancel_document(
        emitter_id=emitter_id,
        document_id=document_id,
        motivo=payload.motivo,
    )
    return SuccessEnvelope(
        data={
            "event": EventResponse.model_validate(event).model_dump(mode="json"),
            "job": JobResponse.model_validate(job).model_dump(mode="json"),
        },
        correlation_id=request.state.correlation_id,
    )


@router.post(
    "/emitters/{emitter_id}/inutilizations",
    response_model=SuccessEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def inutilize_numbers(
    emitter_id: str,
    payload: InutilizeRequest,
    request: Request,
    _principal=Depends(require_fiscal_write),
    service: EventService = Depends(get_event_service),
) -> SuccessEnvelope:
    event, job, range_item = service.inutilize_numbers(
        emitter_id=emitter_id,
        timbrado=payload.timbrado,
        document_type=payload.document_type,
        establishment=payload.establishment,
        point=payload.point,
        numero_desde=payload.numero_desde,
        numero_hasta=payload.numero_hasta,
        motivo=payload.motivo,
    )
    return SuccessEnvelope(
        data={
            "event": EventResponse.model_validate(event).model_dump(mode="json"),
            "job": JobResponse.model_validate(job).model_dump(mode="json"),
            "inutilization": InutilizedRangeResponse.model_validate(range_item).model_dump(mode="json"),
        },
        correlation_id=request.state.correlation_id,
    )


@router.get("/emitters/{emitter_id}/events/{event_id}", response_model=SuccessEnvelope)
def get_event(
    emitter_id: str,
    event_id: str,
    request: Request,
    _principal=Depends(require_fiscal_write),
    service: EventService = Depends(get_event_service),
) -> SuccessEnvelope:
    event, job = service.get_event_for_emitter(emitter_id=emitter_id, event_id=event_id)
    return SuccessEnvelope(
        data={
            "event": EventResponse.model_validate(event).model_dump(mode="json"),
            "job": JobResponse.model_validate(job).model_dump(mode="json") if job else None,
        },
        correlation_id=request.state.correlation_id,
    )
