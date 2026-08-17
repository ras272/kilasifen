"""Pydantic schemas for document APIs."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class DocumentCreateRequest(BaseModel):
    """Document creation payload."""

    external_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)
    document_type: str = Field(min_length=1, max_length=64)
    payload: dict[str, Any] | None = None


class FiscalContractModel(BaseModel):
    """Strict base for public fiscal contract components."""

    model_config = ConfigDict(extra="forbid")


class PublicProcurementPayload(FiscalContractModel):
    modalidad: int | str = Field(
        validation_alias=AliasChoices("modalidad", "modalidad_dncp")
    )
    entidad: int | str
    anio: int | str
    secuencia: int | str
    fecha_codigo: date | str = Field(
        validation_alias=AliasChoices("fecha_codigo", "fecha")
    )


class EconomicActivityPayload(FiscalContractModel):
    codigo: str = Field(min_length=1, max_length=8)
    descripcion: str = Field(min_length=1, max_length=300)


class GenerationResponsiblePayload(FiscalContractModel):
    tipo_documento: int = Field(default=1, ge=1, le=9)
    numero_documento: str = Field(min_length=1, max_length=20)
    nombre: str = Field(min_length=4, max_length=255)
    cargo: str = Field(min_length=2, max_length=100)


class EmitterPayload(FiscalContractModel):
    ruc: str | None = Field(default=None, pattern=r"^\d{5,8}(?:-\d)?$")
    dv: str | None = Field(default=None, pattern=r"^\d$")
    razon_social: str | None = Field(
        default=None,
        min_length=4,
        max_length=255,
        validation_alias=AliasChoices("razon_social", "razonSocial", "nombre"),
    )
    direccion: str | None = Field(default=None, min_length=1, max_length=255)
    numero: str | int | None = None
    complemento_1: str | None = Field(default=None, max_length=255)
    complemento_2: str | None = Field(default=None, max_length=255)
    departamento: int | str | None = None
    descripcion_departamento: str | None = Field(default=None, max_length=100)
    distrito: int | str | None = None
    descripcion_distrito: str | None = Field(default=None, max_length=100)
    ciudad: int | str | None = None
    descripcion_ciudad: str | None = Field(default=None, max_length=100)
    telefono: str | None = Field(default=None, min_length=6, max_length=15)
    email: str | None = Field(default=None, min_length=3, max_length=80)
    actividad_economica: EconomicActivityPayload | None = None
    responsable_generacion: GenerationResponsiblePayload | None = None


class CustomerPayload(FiscalContractModel):
    naturaleza: int | None = Field(default=None, ge=1, le=2)
    tipo_operacion: int | None = Field(default=None, ge=1, le=4)
    tipo_contribuyente: int | None = Field(default=None, ge=1, le=2)
    ruc: str | None = Field(default=None, pattern=r"^\d{5,8}(?:-\d)?$")
    dv: str | None = Field(default=None, pattern=r"^\d$")
    tipo_documento_identidad: int | None = Field(default=None, ge=1, le=9)
    numero_documento_identidad: str | None = Field(default=None, max_length=20)
    razon_social: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        validation_alias=AliasChoices("razon_social", "razonSocial"),
    )
    nombre: str | None = Field(default=None, min_length=1, max_length=255)
    direccion: str | None = Field(default=None, min_length=1, max_length=255)
    numero_casa: str | int | None = None
    pais_codigo: str = Field(default="PRY", min_length=3, max_length=3)
    pais_descripcion: str = Field(default="Paraguay", min_length=3, max_length=100)
    departamento: int | str | None = None
    descripcion_departamento: str | None = Field(default=None, max_length=100)
    distrito: int | str | None = None
    descripcion_distrito: str | None = Field(default=None, max_length=100)
    ciudad: int | str | None = None
    descripcion_ciudad: str | None = Field(default=None, max_length=100)
    telefono: str | None = Field(default=None, max_length=15)
    celular: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=80)
    codigo_cliente: str | None = Field(default=None, min_length=3, max_length=15)
    compras_publicas: PublicProcurementPayload | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> "CustomerPayload":
        naturaleza = self.naturaleza or (1 if self.ruc else 2)
        tipo_operacion = self.tipo_operacion or (1 if self.ruc else 2)
        if naturaleza == 1 and not self.ruc:
            raise ValueError("cliente.ruc is required for a taxpayer receiver")
        if naturaleza == 2 and tipo_operacion != 4:
            if self.tipo_documento_identidad is None:
                raise ValueError("cliente.tipo_documento_identidad is required")
            if not self.numero_documento_identidad:
                raise ValueError("cliente.numero_documento_identidad is required")
        if not self.razon_social and not self.nombre:
            raise ValueError("cliente.razon_social or cliente.nombre is required")
        if tipo_operacion == 3 and self.compras_publicas is None:
            raise ValueError("cliente.compras_publicas is required for B2G")
        return self


class CardPayload(FiscalContractModel):
    marca: int | str
    razon_social_procesadora: str | None = Field(default=None, max_length=60)
    ruc_procesadora: str | None = Field(default=None, pattern=r"^\d{5,8}(?:-\d)?$")
    dv_procesadora: str | None = Field(default=None, pattern=r"^\d$")
    forma_procesamiento: int | str
    codigo_autorizacion: str | int | None = None
    nombre_titular: str | None = Field(default=None, min_length=4, max_length=30)
    ultimos_4: str | int | None = None

    @field_validator("ultimos_4")
    @classmethod
    def validate_last_four(cls, value: str | int | None) -> str | int | None:
        if value is not None and (not str(value).isdigit() or len(str(value)) != 4):
            raise ValueError("tarjeta.ultimos_4 must contain exactly four digits")
        return value


class PaymentPayload(FiscalContractModel):
    tipo: int | str
    monto: Decimal = Field(gt=0, max_digits=19, decimal_places=4)
    moneda: str = Field(default="PYG", min_length=3, max_length=3)
    moneda_descripcion: str | None = Field(default=None, max_length=60)
    tipo_cambio: Decimal | None = Field(default=None, gt=0)
    numero_cheque: str | int | None = None
    banco: str | None = Field(default=None, min_length=4, max_length=20)
    tarjeta: CardPayload | None = None

    @model_validator(mode="after")
    def validate_payment_details(self) -> "PaymentPayload":
        normalized = str(self.tipo).strip().lower()
        if normalized in {"2", "cheque"} and (
            self.numero_cheque is None or not self.banco
        ):
            raise ValueError("numero_cheque and banco are required for cheque payments")
        if normalized in {"3", "4", "tarjeta_credito", "tarjeta_debito"}:
            if self.tarjeta is None:
                raise ValueError("tarjeta is required for card payments")
        return self


class InstallmentPayload(FiscalContractModel):
    monto: Decimal = Field(gt=0, max_digits=19, decimal_places=4)
    fecha_vencimiento: date | str | None = None
    moneda: str = Field(default="PYG", min_length=3, max_length=3)


class CreditPayload(FiscalContractModel):
    tipo: int | Literal["plazo", "cuotas"]
    descripcion: str | None = Field(default=None, min_length=1, max_length=30)
    plazo_descripcion: str | None = Field(default=None, min_length=1, max_length=30)
    monto_entrega_inicial: Decimal | None = Field(default=None, ge=0)
    cuotas: list[InstallmentPayload] | None = Field(default=None, max_length=999)

    @model_validator(mode="after")
    def validate_credit_details(self) -> "CreditPayload":
        normalized = str(self.tipo).strip().lower()
        if normalized in {"1", "plazo"} and not (
            self.descripcion or self.plazo_descripcion
        ):
            raise ValueError("credito.descripcion is required for plazo")
        if normalized in {"2", "cuotas"} and not self.cuotas:
            raise ValueError("credito.cuotas is required for installment credit")
        return self


class OperationConditionPayload(FiscalContractModel):
    tipo: int | Literal["contado", "credito"] = "contado"
    formas_pago: list[PaymentPayload] | None = Field(default=None, max_length=99)
    credito: CreditPayload | None = None

    @model_validator(mode="after")
    def validate_condition_details(self) -> "OperationConditionPayload":
        normalized = str(self.tipo).strip().lower()
        if normalized in {"2", "credito"} and self.credito is None:
            raise ValueError("condicion_operacion.credito is required")
        if normalized in {"1", "contado"} and self.credito is not None:
            raise ValueError("condicion_operacion.credito is not allowed for contado")
        return self


class ItemPayload(FiscalContractModel):
    codigo_interno: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        validation_alias=AliasChoices("codigo_interno", "codigo"),
    )
    descripcion: str = Field(min_length=1, max_length=120)
    unidad_medida: int | str = Field(default=77)
    descripcion_unidad: str | None = Field(default=None, max_length=30)
    cantidad: Decimal = Field(gt=0, max_digits=14, decimal_places=8)
    precio_unitario: Decimal = Field(
        ge=0,
        max_digits=23,
        decimal_places=8,
        validation_alias=AliasChoices("precio_unitario", "precioUnitario"),
    )
    descuento_particular: Decimal = Field(default=Decimal("0"), ge=0)
    descuento_global: Decimal = Field(default=Decimal("0"), ge=0)
    anticipo_particular: Decimal = Field(default=Decimal("0"), ge=0)
    anticipo_global: Decimal = Field(default=Decimal("0"), ge=0)
    cdc_anticipo: str | None = Field(default=None, pattern=r"^\d{44}$")
    afectacion: int | Literal["gravado", "exonerado", "exento", "gravado_parcial"] = (
        "gravado"
    )
    proporcion_gravada: Decimal | None = Field(default=None, gt=0, le=100)
    tasa: Literal[0, 5, 10] = Field(
        default=10,
        validation_alias=AliasChoices("tasa", "iva"),
    )
    tipo_cambio_item: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_tax_and_net_amount(self) -> "ItemPayload":
        affectation = str(self.afectacion).strip().lower()
        if affectation in {"1", "4", "gravado", "gravado_parcial"}:
            if self.tasa not in {5, 10}:
                raise ValueError("items.tasa must be 5 or 10 for taxable IVA items")
        elif self.tasa != 0:
            raise ValueError("items.tasa must be 0 for exempt or exonerated items")
        deductions = (
            self.descuento_particular
            + self.descuento_global
            + self.anticipo_particular
            + self.anticipo_global
        )
        if deductions > self.precio_unitario:
            raise ValueError("item discounts and advances exceed precio_unitario")
        return self


class AssociatedDocumentPayload(FiscalContractModel):
    tipo: int | Literal["electronico", "impreso", "constancia_electronica"] = 1
    cdc: str | None = Field(default=None, pattern=r"^\d{44}$")
    timbrado: str | int | None = None
    establecimiento: str | int | None = None
    punto: str | int | None = None
    numero: str | int | None = None
    fecha_emision: date | str | None = None
    tipo_documento_impreso: int | None = Field(default=None, ge=1, le=4)
    tipo_constancia: int | None = Field(default=None, ge=1, le=2)
    numero_constancia: str | None = Field(default=None, pattern=r"^\d{11}$")
    numero_control: str | None = Field(default=None, pattern=r"^[0-9A-Za-z-]{8}$")

    @model_validator(mode="after")
    def validate_associated_identity(self) -> "AssociatedDocumentPayload":
        normalized = str(self.tipo).strip().lower()
        if normalized in {"1", "electronico"} and not self.cdc:
            raise ValueError("documento_asociado.cdc is required for electronic DTE")
        if normalized in {"2", "impreso"} and not all(
            value is not None
            for value in (
                self.timbrado,
                self.establecimiento,
                self.punto,
                self.numero,
                self.fecha_emision,
            )
        ):
            raise ValueError("printed documento_asociado identity is incomplete")
        if normalized in {"3", "constancia_electronica"} and not (
            self.numero_constancia and self.numero_control
        ):
            raise ValueError("electronic constancia identity is incomplete")
        return self


class BaseFiscalDocumentPayload(FiscalContractModel):
    establecimiento: int | str | None = None
    punto: int | str | None = None
    numero: int | str | None = None
    fecha: date | datetime | str | None = None
    fecha_emision: date | datetime | str | None = None
    moneda: str = Field(default="PYG", min_length=3, max_length=3)
    tipo_cambio: Decimal | None = Field(default=None, gt=0)
    condicion_tipo_cambio: int | None = Field(default=None, ge=1, le=2)
    tipo_transaccion: int | str | None = None
    tipo_impuesto: int | str | None = None
    tipo_contribuyente: int | None = Field(default=None, ge=1, le=2)
    codigo_seguridad: int | str | None = None
    emisor: EmitterPayload | None = None
    cliente: CustomerPayload
    condicion_operacion: OperationConditionPayload | None = None
    condicion: OperationConditionPayload | None = None
    items: list[ItemPayload] = Field(min_length=1, max_length=1_000)
    documento_asociado: (
        AssociatedDocumentPayload | list[AssociatedDocumentPayload] | None
    ) = None
    metadata: dict[str, Any] | None = None

    @field_validator("establecimiento", "punto")
    @classmethod
    def validate_three_digit_code(cls, value: int | str | None) -> int | str | None:
        if value is None:
            return value
        try:
            parsed = int(str(value))
        except ValueError as exc:
            raise ValueError("must be a numeric code between 000 and 999") from exc
        if parsed < 0 or parsed > 999:
            raise ValueError("must be a numeric code between 000 and 999")
        return value

    @field_validator("numero")
    @classmethod
    def validate_document_number(cls, value: int | str | None) -> int | str | None:
        if value is None:
            return value
        try:
            parsed = int(str(value))
        except ValueError as exc:
            raise ValueError("numero must be numeric") from exc
        if parsed < 1 or parsed > 9_999_999:
            raise ValueError("numero must be between 1 and 9999999")
        return value

    @field_validator("codigo_seguridad")
    @classmethod
    def validate_security_code(cls, value: int | str | None) -> int | str | None:
        if value is None:
            return value
        text = str(value)
        if not text.isdigit() or len(text) > 9:
            raise ValueError("codigo_seguridad must contain at most nine digits")
        return value

    @model_validator(mode="after")
    def validate_currency(self) -> "BaseFiscalDocumentPayload":
        currency = self.moneda.upper()
        if currency == "PYG" and (
            self.condicion_tipo_cambio is not None or self.tipo_cambio is not None
        ):
            raise ValueError("exchange-rate fields are not allowed for PYG")
        if currency != "PYG" and self.condicion_tipo_cambio is None:
            raise ValueError("condicion_tipo_cambio is required for foreign currency")
        if self.condicion_tipo_cambio == 1 and self.tipo_cambio is None:
            raise ValueError("tipo_cambio is required when condicion_tipo_cambio is 1")
        return self


class FacturaContractPayload(BaseFiscalDocumentPayload):
    """Validated business payload for Factura endpoint."""

    tipo_documento: Literal[1] = 1
    indicador_presencia: int | str | None = None
    factura: dict[str, Any] | None = None


class NotaCreditoContractPayload(BaseFiscalDocumentPayload):
    """Validated business payload for Nota de Crédito endpoint."""

    tipo_documento: Literal[5] = 5
    motivo_emision: int | str | None = None
    documento_asociado: AssociatedDocumentPayload
    nota_credito: dict[str, Any] | None = None


class FacturaCreateRequest(BaseModel):
    """Typed API contract for factura emission."""

    model_config = ConfigDict(extra="forbid")

    external_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)
    factura: FacturaContractPayload


class NotaCreditoCreateRequest(BaseModel):
    """Typed API contract for nota de crédito emission."""

    model_config = ConfigDict(extra="forbid")

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
