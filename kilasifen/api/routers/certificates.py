"""Certificate API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status

from kilasifen.api.deps import (
    get_certificate_service,
    require_secrets_write,
)
from kilasifen.api.errors import ApiError
from kilasifen.api.schemas.certificates import (
    CertificateData,
    CertificateEnvelope,
    CertificateListData,
    CertificateListEnvelope,
    CertificateResponse,
)
from kilasifen.application.certificates.service import CertificateService
from kilasifen.config import get_settings
from kilasifen.domain.certificates.models import Certificate

router = APIRouter(tags=["certificates"])


@router.post(
    "/emitters/{emitter_id}/certificates",
    response_model=CertificateEnvelope,
    status_code=status.HTTP_201_CREATED,
)
async def upload_certificate(
    emitter_id: str,
    request: Request,
    logical_name: Annotated[str, Form(min_length=1, max_length=128)],
    password: Annotated[str, Form(min_length=1, max_length=512)],
    file: UploadFile = File(...),
    _principal=Depends(require_secrets_write),
    service: CertificateService = Depends(get_certificate_service),
) -> CertificateEnvelope:
    if file.content_type not in {
        "application/octet-stream",
        "application/pkcs12",
        "application/x-pkcs12",
    }:
        raise ApiError(
            status_code=415,
            code="certificates.unsupported_media_type",
            message="A PKCS#12 certificate file is required.",
            category="validation",
        )

    p12_bytes = await _read_bounded_upload(file, get_settings().max_pfx_upload_bytes)
    certificate = service.upload_certificate(
        emitter_id=emitter_id,
        logical_name=logical_name,
        password=password,
        p12_bytes=p12_bytes,
    )
    return _certificate_envelope(request, certificate)


@router.get(
    "/emitters/{emitter_id}/certificates",
    response_model=CertificateListEnvelope,
)
def list_certificates(
    emitter_id: str,
    request: Request,
    _principal=Depends(require_secrets_write),
    service: CertificateService = Depends(get_certificate_service),
) -> CertificateListEnvelope:
    certificates = service.list_certificates(emitter_id)
    return CertificateListEnvelope(
        data=CertificateListData(
            certificates=[
                CertificateResponse.model_validate(certificate)
                for certificate in certificates
            ]
        ),
        correlation_id=request.state.correlation_id,
    )


@router.post(
    "/emitters/{emitter_id}/certificates/{certificate_id}/activate",
    response_model=CertificateEnvelope,
)
def activate_certificate(
    emitter_id: str,
    certificate_id: str,
    request: Request,
    _principal=Depends(require_secrets_write),
    service: CertificateService = Depends(get_certificate_service),
) -> CertificateEnvelope:
    certificate = service.activate_certificate_for_emitter(
        emitter_id=emitter_id,
        certificate_id=certificate_id,
    )
    return _certificate_envelope(request, certificate)


async def _read_bounded_upload(file: UploadFile, limit: int) -> bytes:
    """Read at most one byte beyond the configured limit, then reject safely."""

    content = await file.read(limit + 1)
    if len(content) > limit:
        raise ApiError(
            status_code=413,
            code="certificates.upload_too_large",
            message="Certificate upload exceeds the configured size limit.",
            category="validation",
            details={"max_bytes": limit},
        )
    return content


def _certificate_envelope(
    request: Request,
    certificate: Certificate,
) -> CertificateEnvelope:
    return CertificateEnvelope(
        data=CertificateData(certificate=CertificateResponse.model_validate(certificate)),
        correlation_id=request.state.correlation_id,
    )
