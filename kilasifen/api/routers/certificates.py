"""Certificate API routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status

from kilasifen.api.deps import (
    get_api_key_principal,
    get_certificate_service,
)
from kilasifen.api.schemas.certificates import CertificateResponse
from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.application.certificates.service import CertificateService
from kilasifen.domain.certificates.models import Certificate

router = APIRouter(tags=["certificates"])


@router.post(
    "/emitters/{emitter_id}/certificates",
    response_model=SuccessEnvelope,
    status_code=status.HTTP_201_CREATED,
)
async def upload_certificate(
    emitter_id: str,
    request: Request,
    logical_name: Annotated[str, Form()],
    password: Annotated[str, Form()],
    file: UploadFile = File(...),
    _principal=Depends(get_api_key_principal),
    service: CertificateService = Depends(get_certificate_service),
) -> SuccessEnvelope:
    certificate = service.upload_certificate(
        emitter_id=emitter_id,
        logical_name=logical_name,
        password=password,
        p12_bytes=await file.read(),
    )
    return _certificate_envelope(request, certificate)


@router.get(
    "/emitters/{emitter_id}/certificates",
    response_model=SuccessEnvelope,
)
def list_certificates(
    emitter_id: str,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: CertificateService = Depends(get_certificate_service),
) -> SuccessEnvelope:
    certificates = service.list_certificates(emitter_id)
    return SuccessEnvelope(
        data={
            "certificates": [
                CertificateResponse.model_validate(certificate).model_dump(mode="json")
                for certificate in certificates
            ]
        },
        correlation_id=request.state.correlation_id,
    )


@router.post(
    "/emitters/{emitter_id}/certificates/{certificate_id}/activate",
    response_model=SuccessEnvelope,
)
def activate_certificate(
    emitter_id: str,
    certificate_id: str,
    request: Request,
    _principal=Depends(get_api_key_principal),
    service: CertificateService = Depends(get_certificate_service),
) -> SuccessEnvelope:
    certificate = service.activate_certificate_for_emitter(
        emitter_id=emitter_id,
        certificate_id=certificate_id,
    )
    return _certificate_envelope(request, certificate)


def _certificate_envelope(
    request: Request,
    certificate: Certificate,
) -> SuccessEnvelope:
    return SuccessEnvelope(
        data={
            "certificate": CertificateResponse.model_validate(certificate).model_dump(
                mode="json"
            )
        },
        correlation_id=request.state.correlation_id,
    )
