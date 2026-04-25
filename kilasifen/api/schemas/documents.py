"""Pydantic schemas for document APIs."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentCreateRequest(BaseModel):
    """Document creation payload."""

    external_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)
    document_type: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] | None = None


class DocumentTransportPayload(BaseModel):
    """Transport-level payload used by typed document contracts."""

    generated_xml: str | None = None
    signed_xml: str | None = None
    doc_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_transport_payload(self) -> "DocumentTransportPayload":
        if not self.generated_xml and not self.signed_xml:
            raise ValueError("generated_xml or signed_xml is required")
        return self


class FacturaContractPayload(DocumentTransportPayload):
    """Business payload for Factura endpoint."""

    tipo_documento: int = 1
    establecimiento: int | str | None = None
    punto: int | str | None = None
    numero: int | str | None = None
    fecha: str | None = None
    cliente: dict[str, Any] | None = None
    condicion: dict[str, Any] | None = None
    items: list[dict[str, Any]] | None = None
    factura: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class NotaCreditoContractPayload(DocumentTransportPayload):
    """Business payload for Nota de Crédito endpoint."""

    tipo_documento: int = 5
    establecimiento: int | str | None = None
    punto: int | str | None = None
    numero: int | str | None = None
    fecha: str | None = None
    cliente: dict[str, Any] | None = None
    condicion: dict[str, Any] | None = None
    items: list[dict[str, Any]] | None = None
    documento_asociado: dict[str, Any] | None = None
    nota_credito: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class ReciboContractPayload(DocumentTransportPayload):
    """Business payload for Recibo endpoint."""

    establecimiento: int | str | None = None
    punto: int | str | None = None
    numero: int | str | None = None
    fecha: str | None = None
    concepto: str | None = None
    total: str | int | float | None = None
    cliente: dict[str, Any] | None = None
    condicion: dict[str, Any] | None = None
    usuario: dict[str, Any] | None = None
    documento_asociado: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


class FacturaCreateRequest(BaseModel):
    """Typed API contract for factura emission."""

    external_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)
    factura: FacturaContractPayload


class NotaCreditoCreateRequest(BaseModel):
    """Typed API contract for nota de crédito emission."""

    external_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)
    nota_credito: NotaCreditoContractPayload


class ReciboCreateRequest(BaseModel):
    """Typed API contract for recibo emission."""

    external_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)
    recibo: ReciboContractPayload


class DocumentResponse(BaseModel):
    """Document response payload."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    emitter_id: str
    external_id: str | None
    idempotency_key: str | None
    document_type: str
    payload_snapshot: dict[str, Any] | None
    generated_xml: str | None
    signed_xml: str | None
    sifen_request_xml: str | None
    sifen_response_raw: str | None
    last_query_request_xml: str | None
    last_query_response_raw: str | None
    last_query_at: datetime | None
    cdc: str | None
    internal_status: str
    sifen_status: str | None
    sifen_result_code: str | None
    sifen_result_message: str | None
    created_at: datetime
    updated_at: datetime
