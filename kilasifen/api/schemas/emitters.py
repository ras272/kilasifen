"""Pydantic schemas for emitter APIs."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_LEGAL_NAME_DESCRIPTION = "Razón social (D105, XSD `tdNombre`, 4-255)."
_CSC_PATTERN = r"^[0-9A-Za-z]{32}$"
_CSC_DESCRIPTION = (
    "Código de seguridad del contribuyente: 32 caracteres alfanuméricos. "
    "Nunca se devuelve."
)
_CSC_ID_PATTERN = r"^[0-9]{1,4}$"
_CSC_ID_DESCRIPTION = (
    "IdCSC: de 1 a 4 dígitos entre 1 y 9999; se guarda con cuatro dígitos "
    "(`1` → `0001`)."
)


class EmitterCreateRequest(BaseModel):
    """Emitter creation payload."""

    owner_consumer_id: str | None = Field(default=None, min_length=1, max_length=36)
    external_id: str | None = Field(default=None, max_length=128)
    ruc: str = Field(
        min_length=3,
        max_length=8,
        pattern=r"^[1-9][0-9]*[0-9A-D]?$",
        description="RUC sin DV (D101, XSD `tRuc`).",
    )
    dv: str = Field(
        pattern=r"^[0-9]$",
        description="Dígito verificador del RUC por módulo 11 (D102, 1253).",
    )
    legal_name: str = Field(
        min_length=4, max_length=255, description=_LEGAL_NAME_DESCRIPTION
    )
    tax_environment: Literal["test", "production"]
    csc: str | None = Field(
        default=None, pattern=_CSC_PATTERN, repr=False, description=_CSC_DESCRIPTION
    )
    csc_id: str | None = Field(
        default=None, pattern=_CSC_ID_PATTERN, description=_CSC_ID_DESCRIPTION
    )


class EmitterUpdateRequest(BaseModel):
    """Emitter update payload."""

    legal_name: str | None = Field(
        default=None, min_length=4, max_length=255, description=_LEGAL_NAME_DESCRIPTION
    )
    tax_environment: Literal["test", "production"] | None = None
    csc: str | None = Field(
        default=None, pattern=_CSC_PATTERN, repr=False, description=_CSC_DESCRIPTION
    )
    csc_id: str | None = Field(
        default=None, pattern=_CSC_ID_PATTERN, description=_CSC_ID_DESCRIPTION
    )


class EmitterResponse(BaseModel):
    """Emitter response payload."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    external_id: str | None
    ruc: str
    dv: str
    legal_name: str
    tax_environment: str
    status: str
    csc_configured: bool
    csc_id: str | None
    created_at: datetime
    updated_at: datetime


class EmitterHealthResponse(BaseModel):
    """Emitter operational health payload."""

    model_config = ConfigDict(from_attributes=True)

    emitter_id: str
    emitter_status: str
    has_active_certificate: bool
    certificate_valid_until: datetime | None
    has_active_stamping: bool
    stamping_number: str | None
    stamping_valid_on: date
    queue_queued_count: int
    queue_retry_count: int
    queue_failed_count: int
    last_document_id: str | None
    last_document_status: str | None
    checked_at: datetime
