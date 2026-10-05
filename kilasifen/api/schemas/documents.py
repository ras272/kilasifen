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

from kilasifen.domain.documents.receiver import ReceiverRuleError, resolve_receiver
from kilasifen.engine.sdk.catalogos import (
    descripcion_departamento,
    descripcion_moneda,
    descripcion_pais,
)
from kilasifen.engine.sdk.fiscal import calculate_mod11_dv


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
    """gRespDE (D140-D145): who generated the DE on behalf of the emitter."""

    tipo_documento: Literal[1, 2, 3, 4, 9] = Field(
        description=(
            "iTipIDRespDE (D141): 1 cédula paraguaya, 2 pasaporte, 3 cédula "
            "extranjera, 4 carnet de residencia, 9 otro."
        )
    )
    descripcion_tipo_documento: str | None = Field(
        default=None,
        min_length=9,
        max_length=41,
        description="dDTipIDRespDE: obligatoria solo con `tipo_documento` 9.",
    )
    numero_documento: str = Field(pattern=r"^[0-9A-Za-z-]{1,20}$")
    nombre: str = Field(min_length=4, max_length=255)
    cargo: str = Field(min_length=4, max_length=100, description="dCarRespDE (4-100).")

    @model_validator(mode="after")
    def validate_other_document_type(self) -> "GenerationResponsiblePayload":
        # NT 10 §2.2 (1265): with 9 the real type is described in 9-41 chars.
        if (self.tipo_documento == 9) != (self.descripcion_tipo_documento is not None):
            raise ValueError(
                "responsable_generacion.descripcion_tipo_documento goes only "
                "with tipo_documento 9"
            )
        return self


#: MT v150 D016/E610/E654 (XSD tdDMoneTiPag): the official name of the
#: currency, 3-20 characters (1206/1555).
_CURRENCY_DESCRIPTION_MAX = 20


def _official_currency(value: str | None) -> str | None:
    """Normalize an ISO 4217 code the DE can carry with its official name."""

    if value is None:
        return None
    code = value.strip().upper()
    description = descripcion_moneda(code)
    if description is None or not 3 <= len(description) <= _CURRENCY_DESCRIPTION_MAX:
        raise ValueError(
            "moneda must be an ISO 4217 code of the XSD cMondT whose official "
            "name fits the 20 characters of its description"
        )
    return code


_IGNORED_EMITTER_FIELD = {
    "description": (
        "Obsoleto y sin efecto: los datos de gEmis salen del perfil fiscal del "
        "emisor (`PATCH /v1/emitters/{emitter_id}`)."
    ),
    "json_schema_extra": {"deprecated": True},
}


class EmitterPayload(FiscalContractModel):
    """Optional echo of the emitter identity; it can never change it.

    ``ruc``, ``dv`` and ``razon_social`` are accepted only when they match the
    registered emitter (``422 documents.emisor.identity_mismatch`` otherwise);
    address, contact and activity fields are ignored.
    """

    ruc: str | None = Field(
        default=None,
        max_length=10,
        pattern=r"^[1-9][0-9]*[0-9A-D]?(?:-[0-9])?$",
        description="Tiene que coincidir con el RUC del emisor registrado.",
    )
    dv: str | None = Field(
        default=None,
        pattern=r"^\d$",
        description="Tiene que coincidir con el DV del emisor registrado.",
    )
    razon_social: str | None = Field(
        default=None,
        min_length=4,
        max_length=255,
        validation_alias=AliasChoices("razon_social", "razonSocial", "nombre"),
        description="Tiene que coincidir con la razón social del emisor.",
    )
    direccion: str | None = Field(
        default=None, min_length=1, max_length=255, **_IGNORED_EMITTER_FIELD
    )
    numero: str | int | None = Field(default=None, **_IGNORED_EMITTER_FIELD)
    complemento_1: str | None = Field(
        default=None, max_length=255, **_IGNORED_EMITTER_FIELD
    )
    complemento_2: str | None = Field(
        default=None, max_length=255, **_IGNORED_EMITTER_FIELD
    )
    departamento: int | str | None = Field(default=None, **_IGNORED_EMITTER_FIELD)
    descripcion_departamento: str | None = Field(
        default=None, max_length=100, **_IGNORED_EMITTER_FIELD
    )
    distrito: int | str | None = Field(default=None, **_IGNORED_EMITTER_FIELD)
    descripcion_distrito: str | None = Field(
        default=None, max_length=100, **_IGNORED_EMITTER_FIELD
    )
    ciudad: int | str | None = Field(default=None, **_IGNORED_EMITTER_FIELD)
    descripcion_ciudad: str | None = Field(
        default=None, max_length=100, **_IGNORED_EMITTER_FIELD
    )
    telefono: str | None = Field(
        default=None, min_length=6, max_length=15, **_IGNORED_EMITTER_FIELD
    )
    email: str | None = Field(
        default=None, min_length=3, max_length=80, **_IGNORED_EMITTER_FIELD
    )
    actividad_economica: EconomicActivityPayload | None = Field(
        default=None, **_IGNORED_EMITTER_FIELD
    )
    responsable_generacion: GenerationResponsiblePayload | None = None


class CustomerPayload(FiscalContractModel):
    """Receptor (gDatRec). The document validates it with the rules in force.

    See ``kilasifen.domain.documents.receiver``: 1300 (NT 10), 1320/1301,
    D205-D207 mandatory for a taxpayer, D208-D210 always for a non-taxpayer
    (NT 23, 1335), innominado only in B2C invoices (1333, 1331), and the
    address rules of 1318/1330/NT 03.
    """

    naturaleza: int | None = Field(
        default=None,
        ge=1,
        le=2,
        description="iNatRec: 1 contribuyente, 2 no contribuyente. Por defecto, "
        "1 si hay `ruc`.",
    )
    tipo_operacion: int | None = Field(
        default=None,
        ge=1,
        le=4,
        description="iTiOpe: 1 B2B, 2 B2C, 3 B2G, 4 B2F. Un no contribuyente solo "
        "admite 2 o 4 (1300).",
    )
    tipo_contribuyente: int | None = Field(
        default=None,
        ge=1,
        le=2,
        description="iTiContRec: obligatorio para un contribuyente, sin valor por "
        "defecto.",
    )
    ruc: str | None = Field(
        default=None,
        max_length=10,
        pattern=r"^[1-9][0-9]*[0-9A-D]?(?:-[0-9])?$",
        description="dRucRec (3-8, XSD `tRuc`), opcionalmente con `-DV`.",
    )
    dv: str | None = Field(
        default=None,
        pattern=r"^\d$",
        description="dDVRec: obligatorio con `ruc` (o como `RUC-DV`); módulo 11.",
    )
    tipo_documento_identidad: int | None = Field(
        default=None,
        ge=1,
        le=9,
        description="iTipIDRec: 1-6 o 9; 5 = innominado (solo B2C en facturas).",
    )
    descripcion_tipo_documento: str | None = Field(
        default=None,
        min_length=9,
        max_length=41,
        description="dDTipIDRec del tipo 9: el tipo real de documento (9-41).",
    )
    numero_documento_identidad: str | None = Field(
        default=None,
        pattern=r"^[0-9A-Za-z-]{1,20}$",
        description="dNumIDRec. En innominado se envía siempre `0`.",
    )
    razon_social: str | None = Field(
        default=None,
        min_length=4,
        max_length=255,
        validation_alias=AliasChoices("razon_social", "razonSocial"),
        description="dNomRec. En innominado se envía siempre `Sin Nombre`.",
    )
    nombre: str | None = Field(default=None, min_length=4, max_length=255)
    direccion: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="dDirRec: obligatoria en B2F (1318); con dirección y D202≠4 "
        "son obligatorios `departamento` y `ciudad` (NT 03).",
    )
    numero_casa: str | int | None = None
    pais_codigo: str = Field(
        default="PRY",
        pattern=r"^[A-Z]{3}$",
        description="cPaisRec: distinto de PRY solo en B2F (1320).",
    )
    pais_descripcion: str | None = Field(
        default=None,
        min_length=4,
        max_length=50,
        description="dDesPaisRe: se toma del XSD de países; si se envía tiene "
        "que coincidir (1301).",
    )
    departamento: int | str | None = None
    descripcion_departamento: str | None = Field(default=None, max_length=100)
    distrito: int | str | None = None
    descripcion_distrito: str | None = Field(default=None, max_length=100)
    ciudad: int | str | None = None
    descripcion_ciudad: str | None = Field(default=None, max_length=100)
    telefono: str | None = Field(default=None, min_length=6, max_length=15)
    celular: str | None = Field(default=None, min_length=10, max_length=20)
    email: str | None = Field(default=None, max_length=80)
    codigo_cliente: str | None = Field(default=None, min_length=3, max_length=15)
    compras_publicas: PublicProcurementPayload | None = Field(
        default=None,
        description="gCompPub (E020): opcional en B2G desde la NT 26.",
    )


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
    """gPaConEIni (E606-E611): one payment of a contado operation or of the
    initial delivery of a credit one."""

    tipo: int | str
    monto: Decimal = Field(gt=0, max_digits=19, decimal_places=4)
    moneda: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description=(
            "cMoneTiPag (E609), código ISO 4217. Si se omite, el pago es en la "
            "moneda de la operación."
        ),
    )
    moneda_descripcion: str | None = Field(
        default=None,
        max_length=60,
        description=(
            "Obsoleto y sin efecto: dDMoneTiPag es siempre la descripción "
            "oficial de `moneda` en el XSD (1555)."
        ),
        json_schema_extra={"deprecated": True},
    )
    tipo_cambio: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=9,
        decimal_places=4,
        description=(
            "dTiCamTiPag (E611): obligatorio si `moneda` no es PYG (1556) y "
            "prohibido si es PYG (1557). Si se omite y el pago va en la moneda "
            "de la operación se usa su `tipo_cambio`."
        ),
    )
    numero_cheque: str | int | None = None
    banco: str | None = Field(default=None, min_length=4, max_length=20)
    tarjeta: CardPayload | None = None

    @field_validator("moneda")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        return _official_currency(value)

    @model_validator(mode="after")
    def validate_payment_details(self) -> "PaymentPayload":
        if self.moneda == "PYG" and self.tipo_cambio is not None:
            # MT v150 1557: no E611 for a payment in guaranies.
            raise ValueError("tipo_cambio is not allowed for a payment in PYG")
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
    moneda: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        description=(
            "cMoneCuo (E653), código ISO 4217. Si se omite, la moneda de la "
            "operación."
        ),
    )

    @field_validator("moneda")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        return _official_currency(value)


class CreditPayload(FiscalContractModel):
    tipo: int | Literal["plazo", "cuotas"]
    descripcion: str | None = Field(default=None, min_length=1, max_length=30)
    plazo_descripcion: str | None = Field(default=None, min_length=1, max_length=30)
    monto_entrega_inicial: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=19,
        decimal_places=4,
        description=(
            "dMonEnt (E645), con plazo o cuotas. Exige `formas_pago` en "
            "`condicion_operacion` con los pagos de esa entrega (1551), que "
            "tienen que sumarla."
        ),
    )
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
    formas_pago: list[PaymentPayload] | None = Field(
        default=None,
        max_length=99,
        description=(
            "gPaConEIni. Contado: suman `dTotGralOpe` (tolerancia 0,50); sin "
            "formas se informa un pago en efectivo por el total. Crédito: solo "
            "con `monto_entrega_inicial`, y suman esa entrega (1551/1552)."
        ),
    )
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
    descuento_particular: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=23, decimal_places=8
    )
    descuento_global: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=23,
        decimal_places=8,
        description=(
            "dDescGloItem (EA004). Se calcula como porcentaje_descuento_global * "
            "precio_unitario / 100 (NT 01); si se envía tiene que coincidir con "
            "ese cálculo con una variación de hasta 0,8 (1862)."
        ),
    )
    anticipo_particular: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=23, decimal_places=8
    )
    anticipo_global: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=23, decimal_places=8
    )
    cdc_anticipo: str | None = Field(default=None, pattern=r"^\d{44}$")
    afectacion: int | Literal["gravado", "exonerado", "exento", "gravado_parcial"] = (
        "gravado"
    )
    proporcion_gravada: Decimal | None = Field(
        default=None,
        ge=0,
        le=100,
        max_digits=11,
        decimal_places=8,
        description=(
            "dPropIVA (E733): obligatoria y entre 0 y 100 (sin incluirlos) con "
            "`gravado_parcial` (1906); si se envía vale 100 con `gravado` (1904) "
            "y 0 con `exento` o `exonerado` (1905)."
        ),
    )
    tasa: Literal[0, 5, 10] = Field(
        default=10,
        validation_alias=AliasChoices("tasa", "iva"),
    )
    tipo_cambio_item: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=9,
        decimal_places=4,
        description=(
            "dTiCamIt (E725): obligatorio en cada ítem con condicion_tipo_cambio 2."
        ),
    )

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
            + (self.descuento_global or Decimal("0"))
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
    moneda: str = Field(
        default="PYG",
        min_length=3,
        max_length=3,
        description="cMoneOpe (D015), código ISO 4217 del XSD.",
    )
    tipo_cambio: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=9,
        decimal_places=4,
        description="dTiCam (D018): hasta 4 decimales (XSD tTipoCambioBase).",
    )
    condicion_tipo_cambio: int | None = Field(default=None, ge=1, le=2)
    porcentaje_descuento_global: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        le=100,
        max_digits=11,
        decimal_places=8,
        description=(
            "dPorcDescTotal (F010): porcentaje de descuento global del documento, "
            "0 si no hay. Se aplica a cada ítem sin prorratear: dDescGloItem = "
            "porcentaje * precio_unitario / 100 (NT 01, 1860/1862)."
        ),
    )
    redondeo: Literal["ninguno", "multiplo_50"] = Field(
        default="ninguno",
        description=(
            "dRedon (F013). `ninguno` (por defecto) informa 0. `multiplo_50` "
            "lleva dTotOpe hacia abajo a un múltiplo de 50 Gs (MT v150 §F); "
            "solo en PYG. Nunca se redondea una moneda extranjera."
        ),
    )
    tipo_transaccion: int | str | None = None
    tipo_impuesto: int | str | None = None
    tipo_contribuyente: int | None = Field(
        default=None,
        ge=1,
        le=2,
        description=(
            "Opcional. iTipCont sale del perfil fiscal del emisor; si se envía "
            "tiene que coincidir."
        ),
    )
    codigo_seguridad: int | str | None = Field(
        default=None,
        description=(
            "dCodSeg (B004): opcional. Si se omite, la plataforma genera uno "
            "aleatorio con un CSPRNG y lo conserva para todos los reintentos. "
            "Si se envía tiene que ser aleatorio, de 1 a 999999999, sin relación "
            "con los datos del DE y distinto del número del documento."
        ),
    )
    emisor: EmitterPayload | None = None
    cliente: CustomerPayload
    condicion_operacion: OperationConditionPayload | None = None
    condicion: OperationConditionPayload | None = None
    items: list[ItemPayload] = Field(min_length=1, max_length=1_000)
    documento_asociado: (
        AssociatedDocumentPayload | list[AssociatedDocumentPayload] | None
    ) = None
    metadata: dict[str, Any] | None = None

    @field_validator("moneda")
    @classmethod
    def validate_operation_currency(cls, value: str) -> str:
        return _official_currency(value)

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
        if int(text) == 0:
            # XSD tiCodSe: minInclusive 1, "tampoco debe contener solo ceros".
            raise ValueError("codigo_seguridad must not be zero")
        return value

    @model_validator(mode="after")
    def validate_receiver(self) -> "BaseFiscalDocumentPayload":
        try:
            resolve_receiver(
                self.cliente.model_dump(exclude_none=True),
                document_type=getattr(self, "tipo_documento", 1),
                country_description=descripcion_pais,
                department_description=descripcion_departamento,
                mod11_dv=calculate_mod11_dv,
            )
        except ReceiverRuleError as exc:
            raise ValueError(exc.code) from exc
        return self

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


class NotaDebitoContractPayload(BaseFiscalDocumentPayload):
    """Validated business payload for Nota de Debito endpoint."""

    tipo_documento: Literal[6] = 6
    motivo_emision: int | str | None = None
    documento_asociado: AssociatedDocumentPayload
    nota_debito: dict[str, Any] | None = None


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


class NotaDebitoCreateRequest(BaseModel):
    """Typed API contract for nota de debito emission."""

    model_config = ConfigDict(extra="forbid")

    external_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)
    nota_debito: NotaDebitoContractPayload


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
    fiscal_warnings: list[str] = Field(
        default_factory=list,
        description=(
            "Avisos fiscales detectados al crear el documento, por ejemplo "
            "`documents.transmission.emission_far_from_now`: la fecha de emisión "
            "queda a más de 120 h de la transmisión y el SIFEN la aprobará con "
            "observación 1005 (transmisión extemporánea)."
        ),
    )
    created_at: datetime
    updated_at: datetime
