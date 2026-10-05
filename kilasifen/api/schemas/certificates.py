"""Pydantic schemas for certificate APIs."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from kilasifen.api.schemas.common import SuccessEnvelope


class CertificateResponse(BaseModel):
    """Metadatos de un certificado; nunca incluye la clave ni la contraseña."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    emitter_id: str
    logical_name: str
    fingerprint: str | None
    serial_number: str | None
    subject_summary: str | None
    detected_ruc: str | None
    valid_from: datetime | None
    valid_until: datetime | None
    is_active: bool
    status: str
    created_at: datetime
    updated_at: datetime


class CertificateData(BaseModel):
    """Certificado del emisor."""

    certificate: CertificateResponse


class CertificateListData(BaseModel):
    """Certificados del emisor."""

    certificates: list[CertificateResponse]


class CertificateEnvelope(SuccessEnvelope[CertificateData]):
    """Respuesta con un certificado."""


class CertificateListEnvelope(SuccessEnvelope[CertificateListData]):
    """Respuesta con los certificados del emisor."""
