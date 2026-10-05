"""Pydantic schemas for event APIs."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kilasifen.api.schemas.common import SuccessEnvelope
from kilasifen.api.schemas.jobs import JobResponse


class EventCreateRequest(BaseModel):
    """Evento raw (deprecado, sólo `platform:admin`)."""

    document_id: str
    event_type: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] | None = None


class CancelDocumentRequest(BaseModel):
    """Cancelación de un DTE aprobado."""

    motivo: str = Field(min_length=5, max_length=500)


class InutilizeRequest(BaseModel):
    """Inutilización de un rango de números de un timbrado."""

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
    ] = Field(
        description=(
            "iTiDE del rango. `fe_exportacion`, `fe_importacion` y "
            "`comprobante_retencion` (2, 3 y 8) no son tipos de DE en v150 "
            "(`DE_Types_v150.xsd`): no hay números de esos tipos que inutilizar "
            "y el SIFEN puede responder 4060."
        )
    )
    establishment: str
    point: str
    numero_desde: int = Field(ge=1)
    numero_hasta: int = Field(ge=1)
    motivo: str = Field(min_length=5, max_length=500)
    serie: str | None = Field(
        default=None,
        pattern=r"^[A-Z]{2}$",
        description=(
            "dSerieNum opcional (NT 10 §1.7): serie de la numeración cuando se "
            "reinició después de 9.999.999."
        ),
    )

    @field_validator("establishment", "point")
    @classmethod
    def normalize_three_digits(cls, value: str) -> str:
        parsed = int(str(value).strip())
        if parsed < 0 or parsed > 999:
            raise ValueError("must be within 000..999")
        return f"{parsed:03d}"

class EventResponse(BaseModel):
    """Evento fiscal con su estado y la respuesta del SIFEN."""

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
    """Rango de números inutilizado."""

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


class CreatedEventData(BaseModel):
    """Evento creado y el job que lo transmite."""

    event: EventResponse
    job: JobResponse


class EventWithJobData(BaseModel):
    """Evento y su job, si tiene."""

    event: EventResponse
    job: JobResponse | None


class CreatedInutilizationData(CreatedEventData):
    """Inutilización creada, su rango y los avisos."""

    inutilization: InutilizedRangeResponse
    warnings: list[str] = Field(
        description=(
            "Avisos que no impiden la inutilización, por ejemplo "
            "`inutilization.extemporaneous`."
        )
    )


class CreatedEventEnvelope(SuccessEnvelope[CreatedEventData]):
    """Respuesta de la creación de un evento."""


class EventWithJobEnvelope(SuccessEnvelope[EventWithJobData]):
    """Respuesta con un evento."""


class CreatedInutilizationEnvelope(SuccessEnvelope[CreatedInutilizationData]):
    """Respuesta de la creación de una inutilización."""
