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

    def has_xml_payload(self) -> bool:
        return bool(self.generated_xml or self.signed_xml)


class FacturaContractPayload(DocumentTransportPayload):
    """Business payload for Factura endpoint."""

    tipo_documento: int = 1
    establecimiento: int | str | None = None
    punto: int | str | None = None
    numero: int | str | None = None
    fecha: str | None = None
    fecha_emision: str | None = None
    moneda: str = "PYG"
    tipo_cambio: str | float | int | None = None
    condicion_tipo_cambio: int | str | None = None
    tipo_transaccion: int | str | None = None
    tipo_impuesto: int | str | None = None
    indicador_presencia: int | str | None = None
    tipo_contribuyente: int | str | None = None
    codigo_seguridad: int | str | None = None
    emisor: dict[str, Any] | None = None
    cliente: dict[str, Any] | None = None
    condicion_operacion: dict[str, Any] | None = None
    condicion: dict[str, Any] | None = None
    items: list[dict[str, Any]] | None = None
    documento_asociado: dict[str, Any] | None = None
    factura: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_factura_payload(self) -> "FacturaContractPayload":
        if self.has_xml_payload():
            return self
        if not isinstance(self.cliente, dict):
            raise ValueError("cliente is required when generated_xml/signed_xml is missing")
        if not isinstance(self.items, list) or not self.items:
            raise ValueError("items is required when generated_xml/signed_xml is missing")
        return self


class NotaCreditoContractPayload(DocumentTransportPayload):
    """Business payload for Nota de Crédito endpoint."""

    tipo_documento: int = 5
    establecimiento: int | str | None = None
    punto: int | str | None = None
    numero: int | str | None = None
    fecha: str | None = None
    fecha_emision: str | None = None
    moneda: str = "PYG"
    tipo_cambio: str | float | int | None = None
    condicion_tipo_cambio: int | str | None = None
    tipo_transaccion: int | str | None = None
    tipo_impuesto: int | str | None = None
    tipo_contribuyente: int | str | None = None
    codigo_seguridad: int | str | None = None
    emisor: dict[str, Any] | None = None
    cliente: dict[str, Any] | None = None
    condicion_operacion: dict[str, Any] | None = None
    condicion: dict[str, Any] | None = None
    items: list[dict[str, Any]] | None = None
    motivo_emision: int | str | None = None
    documento_asociado: dict[str, Any] | None = None
    nota_credito: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_nota_credito_payload(self) -> "NotaCreditoContractPayload":
        if self.has_xml_payload():
            return self
        if not isinstance(self.cliente, dict):
            raise ValueError("cliente is required when generated_xml/signed_xml is missing")
        if not isinstance(self.items, list) or not self.items:
            raise ValueError("items is required when generated_xml/signed_xml is missing")
        if not isinstance(self.documento_asociado, dict):
            raise ValueError(
                "documento_asociado is required when generated_xml/signed_xml is missing"
            )
        tipo_documento_asociado = self.documento_asociado.get("tipo")
        has_cdc = bool(self.documento_asociado.get("cdc"))
        if tipo_documento_asociado in {None, 1, "1"} and not has_cdc:
            raise ValueError(
                "documento_asociado.cdc is required when tipo is 1/electronico"
            )
        return self


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
    establishment: str | None
    point: str | None
    document_number: int | None
    created_at: datetime
    updated_at: datetime
