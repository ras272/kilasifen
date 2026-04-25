"""Read-side query API routes."""

from fastapi import APIRouter, Depends, Request

from kilasifen.api.deps import get_api_key_principal, get_query_service
from kilasifen.api.errors import ApiError
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.api.schemas.queries import (
    DocumentQueryResponse,
    RucQueryResponse,
    TaxpayerResponse,
)
from kilasifen.application.queries.service import QueryService

router = APIRouter(prefix="/emitters/{emitter_id}/queries", tags=["queries"])


@router.get("/ruc/{ruc}", response_model=SuccessEnvelope)
def query_ruc(
    emitter_id: str,
    ruc: str,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: QueryService = Depends(get_query_service),
) -> SuccessEnvelope:
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

    return SuccessEnvelope(
        data={
            "ruc_query": RucQueryResponse(
                queried_ruc=outcome.queried_ruc,
                status=outcome.status,
                result_code=outcome.result_code,
                result_message=outcome.result_message,
                taxpayer=taxpayer,
            ).model_dump(mode="json")
        },
        correlation_id=request.state.correlation_id,
    )


@router.get("/documents/{document_id}", response_model=SuccessEnvelope)
def query_document(
    emitter_id: str,
    document_id: str,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: QueryService = Depends(get_query_service),
) -> SuccessEnvelope:
    try:
        document, outcome = service.query_document(
            emitter_id=emitter_id,
            document_id=document_id,
        )
    except ValueError as exc:
        raise ApiError(
            status_code=422,
            code="queries.invalid_cdc",
            message=str(exc),
            category="invalid_request",
        ) from exc

    return SuccessEnvelope(
        data={
            "document_query": DocumentQueryResponse(
                document_id=document.id,
                cdc=outcome.cdc,
                status=outcome.status,
                result_code=outcome.result_code,
                result_message=outcome.result_message,
                content_xml=outcome.content_xml,
                processed_at=outcome.processed_at,
            ).model_dump(mode="json")
        },
        correlation_id=request.state.correlation_id,
    )
