"""Pydantic schemas for emitter APIs."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from kilasifen.domain.emitters.fiscal_profile import (
    EconomicActivity,
    EmitterFiscalProfile,
    FiscalAddress,
    fiscal_profile_to_dict,
)

# XSD tEmail (DE_Types_v150.xsd), anchored for the API validator.
_EMAIL_PATTERN = (
    r"^[0-9a-zA-Z][0-9a-zA-Z.\-_]*@([0-9a-zA-Z][0-9a-zA-Z\-_]*\.)+[a-zA-Z]{2,9}$"
)
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


class _ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EconomicActivityProfile(_ProfileModel):
    """Actividad económica declarada en el RUC (gActEco, D130-D132)."""

    codigo: str = Field(
        pattern=r"^[0-9A-Z]{1,8}$", description="cActEco (Tabla 3, XSD `tcActEco`)."
    )
    descripcion: str = Field(min_length=1, max_length=300, description="dDesActEco.")


class FiscalAddressProfile(_ProfileModel):
    """Dirección y contacto del local que emite el DE (D107-D119)."""

    direccion: str = Field(min_length=1, max_length=255, description="dDirEmi (D107).")
    numero_casa: str = Field(
        pattern=r"^[0-9]{1,6}$",
        description="dNumCas (D108). `0` solo si la dirección no tiene numeración.",
    )
    complemento_1: str | None = Field(default=None, min_length=1, max_length=255)
    complemento_2: str | None = Field(default=None, min_length=1, max_length=255)
    departamento: int = Field(
        ge=1, description="cDepEmi (D111), según `Departamentos_v141.xsd`."
    )
    descripcion_departamento: str | None = Field(
        default=None,
        min_length=6,
        max_length=16,
        description=(
            "dDesDepEmi (D112). Opcional: si se envía tiene que coincidir con el "
            "código; se guarda siempre la descripción oficial."
        ),
    )
    distrito: int | None = Field(default=None, ge=1, le=9999, description="cDisEmi.")
    descripcion_distrito: str | None = Field(
        default=None,
        min_length=1,
        max_length=30,
        description="dDesDisEmi; obligatoria si hay `distrito`.",
    )
    ciudad: int = Field(ge=1, le=99999, description="cCiuEmi (D115).")
    descripcion_ciudad: str = Field(
        min_length=1, max_length=30, description="dDesCiuEmi (D116)."
    )
    telefono: str = Field(
        min_length=6, max_length=15, description="dTelEmi (D117), con prefijo."
    )
    email: str = Field(
        min_length=3, max_length=80, pattern=_EMAIL_PATTERN, description="dEmailE."
    )
    denominacion_sucursal: str | None = Field(
        default=None, min_length=1, max_length=30, description="dDenSuc (D119)."
    )

    def to_domain(self) -> FiscalAddress:
        return FiscalAddress(
            street=self.direccion,
            house_number=self.numero_casa,
            complement_1=self.complemento_1,
            complement_2=self.complemento_2,
            department_code=self.departamento,
            department_description=self.descripcion_departamento or "",
            district_code=self.distrito,
            district_description=self.descripcion_distrito,
            city_code=self.ciudad,
            city_description=self.descripcion_ciudad,
            phone=self.telefono,
            email=self.email,
            branch_name=self.denominacion_sucursal,
        )


class EstablishmentAddressProfile(FiscalAddressProfile):
    """Dirección propia de un establecimiento (`dEst`)."""

    establecimiento: str = Field(
        pattern=r"^[0-9]{3}$", description="Código del establecimiento (C005)."
    )


class EmitterFiscalProfileModel(_ProfileModel):
    """Datos fiscales del emisor tal como figuran en su RUC (gEmis).

    Es la única fuente de `gEmis`: sin este perfil no se puede crear un
    documento. Se reemplaza completo en cada actualización.
    """

    tipo_contribuyente: Literal[1, 2] = Field(
        description="iTipCont (D103): 1 persona física, 2 persona jurídica."
    )
    tipo_regimen: int | None = Field(
        default=None, ge=1, le=8, description="cTipReg (D104, Tabla 1)."
    )
    nombre_fantasia: str | None = Field(
        default=None, min_length=4, max_length=255, description="dNomFanEmi (D106)."
    )
    actividades_economicas: list[EconomicActivityProfile] = Field(
        min_length=1, max_length=9, description="gActEco (D130), de 1 a 9."
    )
    domicilio: FiscalAddressProfile = Field(
        description="Dirección por defecto de los documentos del emisor."
    )
    establecimientos: list[EstablishmentAddressProfile] = Field(
        default_factory=list,
        max_length=999,
        description="Dirección propia de cada establecimiento que la tenga.",
    )

    def to_domain(self) -> EmitterFiscalProfile:
        return EmitterFiscalProfile(
            taxpayer_type=self.tipo_contribuyente,
            regime_type=self.tipo_regimen,
            trade_name=self.nombre_fantasia,
            activities=tuple(
                EconomicActivity(code=item.codigo, description=item.descripcion)
                for item in self.actividades_economicas
            ),
            address=self.domicilio.to_domain(),
            establishments={
                item.establecimiento: item.to_domain()
                for item in self.establecimientos
            },
        )

    @classmethod
    def from_domain(cls, profile: EmitterFiscalProfile) -> "EmitterFiscalProfileModel":
        return cls.model_validate(fiscal_profile_to_dict(profile))


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
    fiscal_profile: EmitterFiscalProfileModel | None = Field(
        default=None,
        description=(
            "Perfil fiscal del RUC. Puede cargarse después, pero sin él no se "
            "pueden crear documentos."
        ),
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
    fiscal_profile: EmitterFiscalProfileModel | None = Field(
        default=None, description="Reemplaza el perfil fiscal completo."
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
    fiscal_profile: EmitterFiscalProfileModel | None
    fiscal_profile_complete: bool = Field(
        description="Falso mientras falte el perfil fiscal: no se puede emitir."
    )
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
