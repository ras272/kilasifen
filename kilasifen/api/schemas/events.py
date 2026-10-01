"""Pydantic schemas for event APIs."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventCreateRequest(BaseModel):
    """Event creation payload."""

    document_id: str
    event_type: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] | None = None


class CancelDocumentRequest(BaseModel):
    """Typed request payload for cancelation events."""

    motivo: str = Field(min_length=5, max_length=500)


class InutilizeRequest(BaseModel):
    """Typed request payload for inutilization events."""

    timbrado: str = Field(pattern=r"^\d{8}$")
    document_type: Literal[
        "factura",
        "fe_exportacion",
        "fe_importacion",
        "autofactura",
        "nota_credito",
        "nota_debito",
        "nota_remision",
        "comprobante_retencion",
    ]
    establishment: str
    point: str
    numero_desde: int = Field(ge=1)
    numero_hasta: int = Field(ge=1)
    motivo: str = Field(min_length=5, max_length=500)

    @field_validator("establishment", "point")
    @classmethod
    def normalize_three_digits(cls, value: str) -> str:
        parsed = int(str(value).strip())
        if parsed < 0 or parsed > 999:
            raise ValueError("must be within 000..999")
        return f"{parsed:03d}"

class EventResponse(BaseModel):
    """Event response payload."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    emitter_id: str
    document_id: str | None
    event_type: str
    input_payload: dict[str, Any] | None
    generated_xml: str | None
    signed_xml: str | None
    sifen_request_xml: str | None
    sifen_response_raw: str | None
    status: str
    sifen_result_code: str | None
    sifen_result_message: str | None
    created_at: datetime
    updated_at: datetime


class InutilizedRangeResponse(BaseModel):
    """API response payload for one inutilized range."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    emitter_id: str
    document_type: str
    establishment: str
    point: str
    numero_desde: int
    numero_hasta: int
    timbrado: str
    event_id: str
    sifen_protocol: str | None
    created_at: datetime
    updated_at: datetime
