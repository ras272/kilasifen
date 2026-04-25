"""Document API routes."""

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from kilasifen.api.deps import get_api_key_principal, get_document_service, get_job_service
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.api.schemas.documents import (
    DocumentCreateRequest,
    DocumentResponse,
    FacturaCreateRequest,
    NotaCreditoCreateRequest,
    ReciboCreateRequest,
)
from kilasifen.api.schemas.jobs import JobResponse
from kilasifen.application.documents.service import DocumentService
from kilasifen.application.jobs.service import JobService

router = APIRouter(tags=["documents"])


@router.post(
    "/emitters/{emitter_id}/documents",
    response_model=SuccessEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def create_document(
    emitter_id: str,
    payload: DocumentCreateRequest,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: DocumentService = Depends(get_document_service),
) -> JSONResponse:
    return _create_document_response(
        request=request,
        service=service,
        emitter_id=emitter_id,
        external_id=payload.external_id,
        idempotency_key=payload.idempotency_key,
        document_type=payload.document_type,
        payload_snapshot=payload.payload,
    )


@router.post(
    "/emitters/{emitter_id}/documents/facturas",
    response_model=SuccessEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def create_factura_document(
    emitter_id: str,
    payload: FacturaCreateRequest,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: DocumentService = Depends(get_document_service),
) -> JSONResponse:
    factura_payload = payload.factura.model_dump(mode="json")
    return _create_document_response(
        request=request,
        service=service,
        emitter_id=emitter_id,
        external_id=payload.external_id,
        idempotency_key=payload.idempotency_key,
        document_type="factura",
        payload_snapshot=_build_typed_payload("factura_v1", factura_payload),
    )


@router.post(
    "/emitters/{emitter_id}/documents/notas-credito",
    response_model=SuccessEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def create_nota_credito_document(
    emitter_id: str,
    payload: NotaCreditoCreateRequest,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: DocumentService = Depends(get_document_service),
) -> JSONResponse:
    nota_credito_payload = payload.nota_credito.model_dump(mode="json")
    return _create_document_response(
        request=request,
        service=service,
        emitter_id=emitter_id,
        external_id=payload.external_id,
        idempotency_key=payload.idempotency_key,
        document_type="nota_credito",
        payload_snapshot=_build_typed_payload("nota_credito_v1", nota_credito_payload),
    )


@router.post(
    "/emitters/{emitter_id}/documents/recibos",
    response_model=SuccessEnvelope,
    status_code=status.HTTP_201_CREATED,
)
def create_recibo_document(
    emitter_id: str,
    payload: ReciboCreateRequest,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: DocumentService = Depends(get_document_service),
) -> JSONResponse:
    recibo_payload = payload.recibo.model_dump(mode="json")
    return _create_document_response(
        request=request,
        service=service,
        emitter_id=emitter_id,
        external_id=payload.external_id,
        idempotency_key=payload.idempotency_key,
        document_type="recibo",
        payload_snapshot=_build_typed_payload("recibo_v1", recibo_payload),
    )


@router.get("/documents/{document_id}", response_model=SuccessEnvelope)
def get_document(
    document_id: str,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: DocumentService = Depends(get_document_service),
    job_service: JobService = Depends(get_job_service),
) -> SuccessEnvelope:
    document = service.get_document(document_id)
    job = job_service.get_for_entity("document", document.id)
    return SuccessEnvelope(
        data={
            "document": DocumentResponse.model_validate(document).model_dump(mode="json"),
            "job": JobResponse.model_validate(job).model_dump(mode="json") if job else None,
        },
        correlation_id=request.state.correlation_id,
    )


def _build_typed_payload(contract: str, typed_payload: dict) -> dict:
    payload = {
        "generated_xml": typed_payload.get("generated_xml"),
        "signed_xml": typed_payload.get("signed_xml"),
        "doc_id": typed_payload.get("doc_id"),
        "typed_contract": {
            "contract": contract,
            "payload": typed_payload,
        },
    }
    return payload


def _create_document_response(
    *,
    request: Request,
    service: DocumentService,
    emitter_id: str,
    external_id: str | None,
    idempotency_key: str | None,
    document_type: str,
    payload_snapshot: dict | None,
) -> JSONResponse:
    document, job, replayed = service.create_document(
        emitter_id=emitter_id,
        external_id=external_id,
        idempotency_key=idempotency_key,
        document_type=document_type,
        payload_snapshot=payload_snapshot,
    )
    envelope = SuccessEnvelope(
        data={
            "document": DocumentResponse.model_validate(document).model_dump(mode="json"),
            "job": JobResponse.model_validate(job).model_dump(mode="json"),
        },
        correlation_id=request.state.correlation_id,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        content=envelope.model_dump(),
    )
