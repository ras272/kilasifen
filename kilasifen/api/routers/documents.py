"""Document API routes."""

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse

from kilasifen.api.deps import get_api_key_principal, get_document_service, get_job_service
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.api.schemas.documents import DocumentCreateRequest, DocumentResponse
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
    document, job, replayed = service.create_document(
        emitter_id=emitter_id,
        external_id=payload.external_id,
        idempotency_key=payload.idempotency_key,
        document_type=payload.document_type,
        payload_snapshot=payload.payload,
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
