"""Pydantic schemas for query APIs."""

from datetime import datetime

from pydantic import BaseModel, Field

from kilasifen.api.schemas.common import SuccessEnvelope


class TaxpayerResponse(BaseModel):
    """Contribuyente según el SIFEN."""

    ruc: str
    dv: str | None = Field(
        default=None,
        description=(
            "Dígito verificador calculado por KilaSifen con el módulo 11 "
            "oficial: el SIFEN no lo devuelve."
        ),
    )
    legal_name: str
    state_code: str | None
    state: str | None
    electronic_taxpayer: bool | None


class RucQueryResponse(BaseModel):
    """Resultado normalizado de la consulta de RUC."""

    queried_ruc: str
    status: str = Field(
        description=(
            "`found`: el SIFEN devolvió el contribuyente (`0502`). `not_found`: "
            "el RUC no existe (`0500`). `error`: cualquier otro código, por "
            "ejemplo `0501`; no dice si el RUC existe."
        )
    )
    result_code: str | None
    result_message: str | None
    taxpayer: TaxpayerResponse | None


class RegisteredEventResponse(BaseModel):
    """Evento que el SIFEN registró sobre el CDC (`xContEv`)."""

    kind: str = Field(
        description=(
            "Tipo de evento: `cancelacion`, `inutilizacion`, "
            "`notificacion_recepcion`, `conformidad`, `disconformidad`, "
            "`desconocimiento`, `endoso`, `transporte` o `nominacion`."
        )
    )
    cdc: str | None
    protocol: str | None = Field(description="dProtAut del evento registrado.")


class DocumentQueryResponse(BaseModel):
    """Resultado normalizado de la consulta del CDC."""

    document_id: str
    cdc: str
    status: str = Field(
        description=(
            "`found` (0422: el CDC es un DTE aprobado), "
            "`not_found_or_not_approved` (0420: no existe o no está aprobado) o "
            "`error` (cualquier otro código)."
        )
    )
    result_code: str | None
    result_message: str | None
    content_xml: str | None = Field(
        description="xContenDE tal como lo envió el SIFEN (contenedor rContDe)."
    )
    processed_at: datetime | None
    sifen_protocol: str | None = Field(
        default=None, description="dProtAut del DTE leído del contenedor."
    )
    cancelled: bool = Field(
        default=False,
        description="`true` si xContEv tiene una cancelación registrada del CDC.",
    )
    events: list[RegisteredEventResponse] = Field(
        default_factory=list,
        description="Eventos registrados del CDC (xContEv).",
    )


class RucQueryData(BaseModel):
    """Resultado de la consulta de RUC en el SIFEN."""

    ruc_query: RucQueryResponse


class DocumentQueryData(BaseModel):
    """Resultado de la consulta del CDC en el SIFEN."""

    document_query: DocumentQueryResponse


class RucQueryEnvelope(SuccessEnvelope[RucQueryData]):
    """Respuesta de la consulta de RUC."""


class DocumentQueryEnvelope(SuccessEnvelope[DocumentQueryData]):
    """Respuesta de la consulta del CDC."""
