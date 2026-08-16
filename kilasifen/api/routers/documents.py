"""Document API routes."""

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse, Response

from kilasifen.api.deps import (
    get_admin_principal,
    get_document_service,
    get_job_service,
    require_emitter_read,
    require_fiscal_write,
)
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.api.schemas.documents import (
    DocumentCreateRequest,
    DocumentResponse,
    FacturaCreateRequest,
    NotaCreditoCreateRequest,
)
from kilasifen.api.schemas.jobs import JobResponse
from kilasifen.application.documents.service import DocumentService
from kilasifen.application.jobs.service import JobService

router = APIRouter(tags=["documents"])


@router.post(
    "/emitters/{emitter_id}/documents",
    response_model=SuccessEnvelope,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"description": "Idempotent replay of the existing document and job."}
    },
    deprecated=True,
    summary="Create a raw document (platform administrators only)",
)
def create_document(
    emitter_id: str,
    payload: DocumentCreateRequest,
    request: Request,
    _principal=Depends(get_admin_principal),
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
    responses={
        200: {"description": "Idempotent replay of the existing document and job."}
    },
)
def create_factura_document(
    emitter_id: str,
    payload: FacturaCreateRequest,
    request: Request,
    _principal=Depends(require_fiscal_write),
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
    responses={
        200: {"description": "Idempotent replay of the existing document and job."}
    },
)
def create_nota_credito_document(
    emitter_id: str,
    payload: NotaCreditoCreateRequest,
    request: Request,
    _principal=Depends(require_fiscal_write),
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


@router.get(
    "/emitters/{emitter_id}/documents/{document_id}", response_model=SuccessEnvelope
)
def get_document(
    emitter_id: str,
    document_id: str,
    request: Request,
    _principal=Depends(require_emitter_read),
    service: DocumentService = Depends(get_document_service),
    job_service: JobService = Depends(get_job_service),
) -> SuccessEnvelope:
    document = service.get_document_for_emitter(
        emitter_id=emitter_id, document_id=document_id
    )
    job = job_service.get_for_entity("document", document.id)
    return SuccessEnvelope(
        data={
            "document": DocumentResponse.model_validate(document).model_dump(
                mode="json"
            ),
            "job": JobResponse.model_validate(job).model_dump(mode="json")
            if job
            else None,
        },
        correlation_id=request.state.correlation_id,
    )


@router.get("/emitters/{emitter_id}/documents", response_model=SuccessEnvelope)
def list_documents(
    emitter_id: str,
    request: Request,
    limit: int = 50,
    offset: int = 0,
    internal_status: str | None = None,
    document_type: str | None = None,
    external_id: str | None = None,
    cdc: str | None = None,
    _principal=Depends(require_emitter_read),
    service: DocumentService = Depends(get_document_service),
    job_service: JobService = Depends(get_job_service),
) -> SuccessEnvelope:
    documents = service.list_documents(
        emitter_id=emitter_id,
        limit=limit,
        offset=offset,
        internal_status=internal_status,
        document_type=document_type,
        external_id=external_id,
        cdc=cdc,
    )
    jobs_by_document_id = {
        document.id: job_service.get_for_entity("document", document.id)
        for document in documents
    }
    return SuccessEnvelope(
        data={
            "documents": [
                {
                    "document": DocumentResponse.model_validate(document).model_dump(
                        mode="json"
                    ),
                    "job": (
                        JobResponse.model_validate(
                            jobs_by_document_id[document.id]
                        ).model_dump(mode="json")
                        if jobs_by_document_id[document.id]
                        else None
                    ),
                }
                for document in documents
            ],
            "pagination": {"limit": limit, "offset": offset, "count": len(documents)},
        },
        correlation_id=request.state.correlation_id,
    )


@router.get("/emitters/{emitter_id}/documents/{document_id}/xml")
def get_document_xml(
    emitter_id: str,
    document_id: str,
    _principal=Depends(require_emitter_read),
    service: DocumentService = Depends(get_document_service),
) -> Response:
    xml_content = service.get_document_xml_for_emitter(
        emitter_id=emitter_id,
        document_id=document_id,
    )
    return Response(content=xml_content, media_type="application/xml")


@router.get("/emitters/{emitter_id}/documents/{document_id}/kude")
def get_document_kude(
    emitter_id: str,
    document_id: str,
    _principal=Depends(require_emitter_read),
    service: DocumentService = Depends(get_document_service),
) -> Response:
    pdf_bytes = service.get_document_kude(
        emitter_id=emitter_id,
        document_id=document_id,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="kude-{document_id}.pdf"',
        },
    )


@router.get(
    "/emitters/{emitter_id}/documents/{document_id}/kude/data",
    response_model=SuccessEnvelope,
)
def get_document_kude_data(
    emitter_id: str,
    document_id: str,
    request: Request,
    _principal=Depends(require_emitter_read),
    service: DocumentService = Depends(get_document_service),
) -> SuccessEnvelope:
    data = service.get_document_kude_data(
        emitter_id=emitter_id,
        document_id=document_id,
    )
    return SuccessEnvelope(
        data=data,
        correlation_id=request.state.correlation_id,
    )


def _build_typed_payload(contract: str, typed_payload: dict) -> dict:
    payload = {
        "generated_xml": None,
        "signed_xml": None,
        "doc_id": None,
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
            "document": DocumentResponse.model_validate(document).model_dump(
                mode="json"
            ),
            "job": JobResponse.model_validate(job).model_dump(mode="json"),
        },
        correlation_id=request.state.correlation_id,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        content=envelope.model_dump(),
    )
