"""Event API routes."""

from fastapi import APIRouter, Depends, Request, status

from kilasifen.api.deps import (
    get_admin_principal,
    get_event_service,
    require_fiscal_write,
)
from kilasifen.api.schemas.events import (
    CancelDocumentRequest,
    CreatedEventData,
    CreatedEventEnvelope,
    CreatedInutilizationData,
    CreatedInutilizationEnvelope,
    EventCreateRequest,
    EventResponse,
    EventWithJobData,
    EventWithJobEnvelope,
    InutilizedRangeResponse,
    InutilizeRequest,
)
from kilasifen.api.schemas.jobs import JobResponse
from kilasifen.application.events.service import EventService
from kilasifen.domain.events.models import Event
from kilasifen.domain.jobs.models import Job

router = APIRouter(tags=["events"])


@router.post(
    "/emitters/{emitter_id}/events",
    response_model=CreatedEventEnvelope,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
    summary="Create a raw fiscal event (platform administrators only)",
)
def create_event(
    emitter_id: str,
    payload: EventCreateRequest,
    request: Request,
    _principal=Depends(get_admin_principal),
    service: EventService = Depends(get_event_service),
) -> CreatedEventEnvelope:
    event, job = service.create_event(
        emitter_id=emitter_id,
        document_id=payload.document_id,
        event_type=payload.event_type,
        input_payload=payload.payload,
    )
    return CreatedEventEnvelope(
        data=_created_event(event, job),
        correlation_id=request.state.correlation_id,
    )


@router.post(
    "/emitters/{emitter_id}/documents/{document_id}/cancel",
    response_model=CreatedEventEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def cancel_document(
    emitter_id: str,
    document_id: str,
    payload: CancelDocumentRequest,
    request: Request,
    _principal=Depends(require_fiscal_write),
    service: EventService = Depends(get_event_service),
) -> CreatedEventEnvelope:
    event, job = service.cancel_document(
        emitter_id=emitter_id,
        document_id=document_id,
        motivo=payload.motivo,
    )
    return CreatedEventEnvelope(
        data=_created_event(event, job),
        correlation_id=request.state.correlation_id,
    )


@router.post(
    "/emitters/{emitter_id}/inutilizations",
    response_model=CreatedInutilizationEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def inutilize_numbers(
    emitter_id: str,
    payload: InutilizeRequest,
    request: Request,
    _principal=Depends(require_fiscal_write),
    service: EventService = Depends(get_event_service),
) -> CreatedInutilizationEnvelope:
    """Inutiliza un rango de números de un timbrado del emisor.

    Se pueden inutilizar números sin documento, rechazados, fallidos por
    validación local o en cola abortados; nunca un DTE aprobado o cancelado ni
    un documento que pueda estar en el SIFEN. Pasado el día 15 del mes
    siguiente al consumo del número (plazo de 360 h, MT v150 §6.2.1), la
    respuesta trae el aviso `inutilization.extemporaneous` y la inutilización
    se envía igual: el MT v150 §11.6.2 no prevé un código de rechazo por
    plazo, pero cómo responde el SIFEN fuera de plazo no está verificado.
    """

    event, job, range_item, warnings = service.inutilize_numbers(
        emitter_id=emitter_id,
        timbrado=payload.timbrado,
        document_type=payload.document_type,
        establishment=payload.establishment,
        point=payload.point,
        numero_desde=payload.numero_desde,
        numero_hasta=payload.numero_hasta,
        motivo=payload.motivo,
        serie=payload.serie,
    )
    return CreatedInutilizationEnvelope(
        data=CreatedInutilizationData(
            event=EventResponse.model_validate(event),
            job=JobResponse.model_validate(job),
            inutilization=InutilizedRangeResponse.model_validate(range_item),
            warnings=list(warnings),
        ),
        correlation_id=request.state.correlation_id,
    )


@router.get(
    "/emitters/{emitter_id}/events/{event_id}",
    response_model=EventWithJobEnvelope,
)
def get_event(
    emitter_id: str,
    event_id: str,
    request: Request,
    _principal=Depends(require_fiscal_write),
    service: EventService = Depends(get_event_service),
) -> EventWithJobEnvelope:
    event, job = service.get_event_for_emitter(emitter_id=emitter_id, event_id=event_id)
    return EventWithJobEnvelope(
        data=EventWithJobData(
            event=EventResponse.model_validate(event),
            job=JobResponse.model_validate(job) if job else None,
        ),
        correlation_id=request.state.correlation_id,
    )


def _created_event(event: Event, job: Job) -> CreatedEventData:
    return CreatedEventData(
        event=EventResponse.model_validate(event),
        job=JobResponse.model_validate(job),
    )
