"""Document API routes."""

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse, Response

from kilasifen.api.deps import (
    get_admin_principal,
    get_document_service,
    get_job_service,
    require_emitter_read,
    require_fiscal_write,
)
from kilasifen.api.schemas.common import Pagination
from kilasifen.api.schemas.documents import (
    CreatedDocumentData,
    CreatedDocumentEnvelope,
    DocumentCreateRequest,
    DocumentListData,
    DocumentListEnvelope,
    DocumentResponse,
    DocumentWithJobData,
    DocumentWithJobEnvelope,
    FacturaCreateRequest,
    KudeData,
    KudeEnvelope,
    NotaCreditoCreateRequest,
    NotaDebitoCreateRequest,
)
from kilasifen.api.schemas.jobs import JobResponse
from kilasifen.application.documents.service import DocumentService
from kilasifen.application.jobs.service import JobService
from kilasifen.domain.documents.models import Document
from kilasifen.domain.jobs.models import Job
from kilasifen.domain.sandbox import SandboxOutcome

router = APIRouter(tags=["documents"])


def _download_response(media_type: str, description: str) -> dict:
    """Declare a non-JSON 200 so the reference does not show it as JSON."""

    schema = {"type": "string"}
    if media_type == "application/pdf":
        schema["format"] = "binary"
    return {"description": description, "content": {media_type: {"schema": schema}}}


# A replayed idempotency key answers 200 with the same envelope as the 201.
_REPLAY_RESPONSES: dict[int | str, dict] = {
    200: {
        "model": CreatedDocumentEnvelope,
        "description": (
            "Reintento idempotente: el documento y el job ya existentes con esa "
            "`idempotency_key`; no se crea otro documento."
        ),
    }
}


def get_sandbox_outcome(
    value: SandboxOutcome | None = Header(
        default=None,
        alias="X-Kila-Test-Outcome",
        description=(
            "Fuerza un resultado determinístico del SIFEN. Sólo en un "
            "despliegue con `KILA_SIFEN_ENVIRONMENT=test`; en otro responde "
            "`422 sandbox.test_runtime_required`."
        ),
    ),
) -> SandboxOutcome | None:
    """Parse the typed sandbox outcome header."""

    return value


@router.post(
    "/emitters/{emitter_id}/documents",
    response_model=CreatedDocumentEnvelope,
    status_code=status.HTTP_201_CREATED,
    responses=_REPLAY_RESPONSES,
    deprecated=True,
    summary="Create a raw document (platform administrators only)",
    description=(
        "Deprecado y sólo para `platform:admin`. `payload.generated_xml` debe "
        "ser un `rDE` sin firmar que valide contra el XSD oficial; la "
        "plataforma lo firma con el certificado del emisor. `signed_xml` se "
        "rechaza con `422`."
    ),
)
def create_document(
    emitter_id: str,
    payload: DocumentCreateRequest,
    request: Request,
    sandbox_outcome: SandboxOutcome | None = Depends(get_sandbox_outcome),
    _principal=Depends(get_admin_principal),
    service: DocumentService = Depends(get_document_service),
) -> JSONResponse:
    document, job, replayed = service.create_raw_document(
        emitter_id=emitter_id,
        external_id=payload.external_id,
        idempotency_key=payload.idempotency_key,
        document_type=payload.document_type,
        payload_snapshot=payload.payload,
        sandbox_outcome=sandbox_outcome,
    )
    return _document_created_response(request, document, job, replayed)


@router.post(
    "/emitters/{emitter_id}/documents/facturas",
    response_model=CreatedDocumentEnvelope,
    status_code=status.HTTP_201_CREATED,
    responses=_REPLAY_RESPONSES,
)
def create_factura_document(
    emitter_id: str,
    payload: FacturaCreateRequest,
    request: Request,
    sandbox_outcome: SandboxOutcome | None = Depends(get_sandbox_outcome),
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
        sandbox_outcome=sandbox_outcome,
    )


@router.post(
    "/emitters/{emitter_id}/documents/notas-credito",
    response_model=CreatedDocumentEnvelope,
    status_code=status.HTTP_201_CREATED,
    responses=_REPLAY_RESPONSES,
)
def create_nota_credito_document(
    emitter_id: str,
    payload: NotaCreditoCreateRequest,
    request: Request,
    sandbox_outcome: SandboxOutcome | None = Depends(get_sandbox_outcome),
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
        sandbox_outcome=sandbox_outcome,
    )


@router.post(
    "/emitters/{emitter_id}/documents/notas-debito",
    response_model=CreatedDocumentEnvelope,
    status_code=status.HTTP_201_CREATED,
    responses=_REPLAY_RESPONSES,
)
def create_nota_debito_document(
    emitter_id: str,
    payload: NotaDebitoCreateRequest,
    request: Request,
    sandbox_outcome: SandboxOutcome | None = Depends(get_sandbox_outcome),
    _principal=Depends(require_fiscal_write),
    service: DocumentService = Depends(get_document_service),
) -> JSONResponse:
    nota_debito_payload = payload.nota_debito.model_dump(mode="json")
    return _create_document_response(
        request=request,
        service=service,
        emitter_id=emitter_id,
        external_id=payload.external_id,
        idempotency_key=payload.idempotency_key,
        document_type="nota_debito",
        payload_snapshot=_build_typed_payload("nota_debito_v1", nota_debito_payload),
        sandbox_outcome=sandbox_outcome,
    )


@router.get(
    "/emitters/{emitter_id}/documents/{document_id}",
    response_model=DocumentWithJobEnvelope,
)
def get_document(
    emitter_id: str,
    document_id: str,
    request: Request,
    _principal=Depends(require_emitter_read),
    service: DocumentService = Depends(get_document_service),
    job_service: JobService = Depends(get_job_service),
) -> DocumentWithJobEnvelope:
    document = service.get_document_for_emitter(
        emitter_id=emitter_id, document_id=document_id
    )
    job = job_service.get_for_entity("document", document.id)
    return DocumentWithJobEnvelope(
        data=_document_with_job(document, job),
        correlation_id=request.state.correlation_id,
    )


@router.get(
    "/emitters/{emitter_id}/documents",
    response_model=DocumentListEnvelope,
)
def list_documents(
    emitter_id: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    internal_status: str | None = Query(
        default=None,
        description=(
            "Estado exacto: `queued`, `processing`, `submitting`, `submitted`, "
            "`retry_pending`, `reconciliation_required`, `approved`, "
            "`approved_with_observation`, `rejected`, `failed`, `cancelled` o "
            "`inutilized`. Un valor desconocido devuelve una página vacía."
        ),
    ),
    document_type: str | None = Query(
        default=None,
        description="`factura`, `nota_credito` o `nota_debito`.",
    ),
    external_id: str | None = Query(
        default=None, description="Identificador del documento en el ERP."
    ),
    cdc: str | None = Query(default=None, description="CDC de 44 dígitos."),
    _principal=Depends(require_emitter_read),
    service: DocumentService = Depends(get_document_service),
    job_service: JobService = Depends(get_job_service),
) -> DocumentListEnvelope:
    documents = service.list_documents(
        emitter_id=emitter_id,
        limit=limit,
        offset=offset,
        internal_status=internal_status,
        document_type=document_type,
        external_id=external_id,
        cdc=cdc,
    )
    jobs = job_service.latest_for_entities(
        "document", [document.id for document in documents]
    )
    return DocumentListEnvelope(
        data=DocumentListData(
            documents=[
                _document_with_job(document, jobs.get(document.id))
                for document in documents
            ],
            pagination=Pagination(limit=limit, offset=offset, count=len(documents)),
        ),
        correlation_id=request.state.correlation_id,
    )


@router.get(
    "/emitters/{emitter_id}/documents/{document_id}/xml",
    response_class=Response,
    responses={
        200: _download_response(
            "application/xml",
            "XML firmado del DE; antes de firmarlo, el XML generado. Sin ninguno "
            "de los dos responde `409 documents.xml_not_available`.",
        )
    },
)
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


_KUDE_AVAILABILITY = (
    "Disponible para documentos aprobados y para los que siguen en camino "
    "al SIFEN (`queued`, `processing`, `submitting`, `submitted`, "
    "`retry_pending`, `reconciliation_required`): con validación posterior el "
    "KuDE puede entregarse antes de la aprobación, pero sólo vale si el SIFEN "
    "aprueba el DE (MT v150 §6.2 y §6.4). Un documento `rejected`, `failed`, "
    "`inutilized` o `cancelled`, o en cualquier otro estado, responde `409 "
    "documents.kude_not_available` con el estado en `details.internal_status`."
)


@router.get(
    "/emitters/{emitter_id}/documents/{document_id}/kude",
    response_class=Response,
    responses={
        200: _download_response(
            "application/pdf",
            "PDF del KuDE (`Content-Disposition: inline`).",
        )
    },
    description=(
        "KuDE en PDF del XML firmado, con el código QR en la primera página. "
        + _KUDE_AVAILABILITY
    ),
)
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
    response_model=KudeEnvelope,
    description=(
        "Datos del KuDE leídos del XML firmado; montos y fechas van con el "
        "texto literal del XML. " + _KUDE_AVAILABILITY
    ),
)
def get_document_kude_data(
    emitter_id: str,
    document_id: str,
    request: Request,
    _principal=Depends(require_emitter_read),
    service: DocumentService = Depends(get_document_service),
) -> KudeEnvelope:
    data = service.get_document_kude_data(
        emitter_id=emitter_id,
        document_id=document_id,
    )
    return KudeEnvelope(
        data=KudeData.model_validate(data),
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
    sandbox_outcome: SandboxOutcome | None,
) -> JSONResponse:
    document, job, replayed = service.create_document(
        emitter_id=emitter_id,
        external_id=external_id,
        idempotency_key=idempotency_key,
        document_type=document_type,
        payload_snapshot=payload_snapshot,
        sandbox_outcome=sandbox_outcome,
    )
    return _document_created_response(request, document, job, replayed)


def _document_created_response(
    request: Request,
    document: Document,
    job: Job,
    replayed: bool,
) -> JSONResponse:
    envelope = CreatedDocumentEnvelope(
        data=CreatedDocumentData(
            document=DocumentResponse.model_validate(document),
            job=JobResponse.model_validate(job),
        ),
        correlation_id=request.state.correlation_id,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK if replayed else status.HTTP_201_CREATED,
        content=envelope.model_dump(mode="json"),
    )


def _document_with_job(document: Document, job: Job | None) -> DocumentWithJobData:
    return DocumentWithJobData(
        document=DocumentResponse.model_validate(document),
        job=JobResponse.model_validate(job) if job else None,
    )
