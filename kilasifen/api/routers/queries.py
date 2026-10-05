"""Read-side query API routes."""

from fastapi import APIRouter, Depends, Request

from kilasifen.api.deps import (
    get_query_service,
    require_emitter_read,
    require_fiscal_write,
)
from kilasifen.api.errors import ApiError
from kilasifen.api.schemas.queries import (
    DocumentQueryData,
    DocumentQueryEnvelope,
    DocumentQueryResponse,
    RegisteredEventResponse,
    RucQueryData,
    RucQueryEnvelope,
    RucQueryResponse,
    TaxpayerResponse,
)
from kilasifen.application.queries.service import QueryService

router = APIRouter(prefix="/emitters/{emitter_id}/queries", tags=["queries"])


@router.get("/ruc/{ruc}", response_model=RucQueryEnvelope)
def query_ruc(
    emitter_id: str,
    ruc: str,
    request: Request,
    _principal=Depends(require_emitter_read),
    service: QueryService = Depends(get_query_service),
) -> RucQueryEnvelope:
    try:
        outcome = service.query_ruc(emitter_id=emitter_id, ruc=ruc)
    except ValueError as exc:
        raise ApiError(
            status_code=422,
            code="queries.invalid_ruc",
            message=str(exc),
            category="invalid_request",
        ) from exc

    taxpayer = None
    if outcome.taxpayer_ruc and outcome.taxpayer_legal_name:
        taxpayer = TaxpayerResponse(
            ruc=outcome.taxpayer_ruc,
            legal_name=outcome.taxpayer_legal_name,
            state_code=outcome.taxpayer_state_code,
            state=outcome.taxpayer_state,
            electronic_taxpayer=outcome.electronic_taxpayer,
        )

    return RucQueryEnvelope(
        data=RucQueryData(
            ruc_query=RucQueryResponse(
                queried_ruc=outcome.queried_ruc,
                status=outcome.status,
                result_code=outcome.result_code,
                result_message=outcome.result_message,
                taxpayer=taxpayer,
            )
        ),
        correlation_id=request.state.correlation_id,
    )


@router.get(
    "/documents/{document_id}", response_model=DocumentQueryEnvelope
)
def query_document(
    emitter_id: str,
    document_id: str,
    request: Request,
    _principal=Depends(require_emitter_read),
    service: QueryService = Depends(get_query_service),
) -> DocumentQueryEnvelope:
    return _query_document_response(
        emitter_id=emitter_id,
        document_id=document_id,
        request=request,
        service=service,
        reconcile=False,
    )


@router.post(
    "/documents/{document_id}/reconcile",
    response_model=DocumentQueryEnvelope,
)
def reconcile_document(
    emitter_id: str,
    document_id: str,
    request: Request,
    _principal=Depends(require_fiscal_write),
    service: QueryService = Depends(get_query_service),
) -> DocumentQueryEnvelope:
    """Consulta el CDC y registra la respuesta del SIFEN; no transmite el DE.

    Con 0422 un documento pendiente queda aprobado (o cancelado si hay una
    cancelación registrada en `xContEv`) y uno aprobado con una cancelación
    registrada queda cancelado. Que el SIFEN devuelva 0422 con el evento para
    un DTE cancelado, y la forma exacta de `xContEv`, no están verificados en
    el ambiente de test. Con 0420 un documento pendiente que no se está
    enviando vuelve a la cola: su próximo intento reenvía el mismo DE firmado
    (mismo CDC).
    """

    return _query_document_response(
        emitter_id=emitter_id,
        document_id=document_id,
        request=request,
        service=service,
        reconcile=True,
    )


def _query_document_response(
    *,
    emitter_id: str,
    document_id: str,
    request: Request,
    service: QueryService,
    reconcile: bool,
) -> DocumentQueryEnvelope:
    try:
        document, outcome = service.query_document(
            emitter_id=emitter_id,
            document_id=document_id,
            reconcile=reconcile,
        )
    except ValueError as exc:
        raise ApiError(
            status_code=422,
            code="queries.invalid_cdc",
            message=str(exc),
            category="invalid_request",
        ) from exc

    return DocumentQueryEnvelope(
        data=DocumentQueryData(
            document_query=DocumentQueryResponse(
                document_id=document.id,
                cdc=outcome.cdc,
                status=outcome.status,
                result_code=outcome.result_code,
                result_message=outcome.result_message,
                content_xml=outcome.content_xml,
                processed_at=outcome.processed_at,
                sifen_protocol=outcome.protocol,
                cancelled=outcome.cancelled,
                events=[
                    RegisteredEventResponse(
                        kind=event.kind,
                        cdc=event.cdc,
                        protocol=event.protocol,
                    )
                    for event in (
                        outcome.container.events if outcome.container else ()
                    )
                ],
            )
        ),
        correlation_id=request.state.correlation_id,
    )
