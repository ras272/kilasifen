"""Fiscal profile of an emitter: the only source of the ``gEmis`` data.

The Manual Tecnico v150 (D103-D132, pp. 69-70) requires the emitter data of
every DE to "correspond to what is declared in the RUC": taxpayer type,
address of the issuing premises, phone, email and economic activities. None
of them may be invented, so the platform keeps them per emitter and refuses
to build a document while the profile is missing.

The address belongs to the premises that issue the DE (D107 "Direccion del
local donde se emite el DE"): the profile carries a default fiscal address
and optional overrides per establishment code (``dEst``, C005).

The persisted form is a plain dictionary with the same Spanish keys the API
exposes, so the stored JSON mirrors the public contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EconomicActivity:
    """One ``gActEco`` group (D131 ``cActEco``, D132 ``dDesActEco``)."""

    code: str
    description: str


@dataclass(frozen=True, slots=True)
class FiscalAddress:
    """Address and contact data of the premises that issue the DE."""

    street: str  # D107 dDirEmi
    house_number: str  # D108 dNumCas ("0" when the address has no number)
    department_code: int  # D111 cDepEmi
    department_description: str  # D112 dDesDepEmi
    city_code: int  # D115 cCiuEmi
    city_description: str  # D116 dDesCiuEmi
    phone: str  # D117 dTelEmi
    email: str  # D118 dEmailE
    complement_1: str | None = None  # D109 dCompDir1
    complement_2: str | None = None  # D110 dCompDir2
    district_code: int | None = None  # D113 cDisEmi
    district_description: str | None = None  # D114 dDesDisEmi
    branch_name: str | None = None  # D119 dDenSuc


@dataclass(frozen=True, slots=True)
class EmitterFiscalProfile:
    """Fiscal data of the emitter as declared in its RUC."""

    taxpayer_type: int  # D103 iTipCont: 1 persona fisica, 2 persona juridica
    activities: tuple[EconomicActivity, ...]  # D130 gActEco, 1 to 9
    address: FiscalAddress
    regime_type: int | None = None  # D104 cTipReg
    trade_name: str | None = None  # D106 dNomFanEmi
    establishments: dict[str, FiscalAddress] = field(default_factory=dict)

    def address_for(self, establishment: str) -> FiscalAddress:
        """Return the address of ``establishment`` or the default one."""

        return self.establishments.get(establishment, self.address)


def fiscal_profile_to_dict(profile: EmitterFiscalProfile) -> dict:
    """Serialize a profile with the public (Spanish) field names."""

    return {
        "tipo_contribuyente": profile.taxpayer_type,
        "tipo_regimen": profile.regime_type,
        "nombre_fantasia": profile.trade_name,
        "actividades_economicas": [
            {"codigo": activity.code, "descripcion": activity.description}
            for activity in profile.activities
        ],
        "domicilio": _address_to_dict(profile.address),
        "establecimientos": [
            {"establecimiento": code, **_address_to_dict(address)}
            for code, address in sorted(profile.establishments.items())
        ],
    }


def fiscal_profile_from_dict(data: dict) -> EmitterFiscalProfile:
    """Rebuild a profile from :func:`fiscal_profile_to_dict` output.

    It only maps the structure; validation belongs to the application layer.
    """

    return EmitterFiscalProfile(
        taxpayer_type=int(data["tipo_contribuyente"]),
        regime_type=_optional_int(data.get("tipo_regimen")),
        trade_name=data.get("nombre_fantasia"),
        activities=tuple(
            EconomicActivity(code=item["codigo"], description=item["descripcion"])
            for item in data["actividades_economicas"]
        ),
        address=_address_from_dict(data["domicilio"]),
        establishments={
            item["establecimiento"]: _address_from_dict(item)
            for item in data.get("establecimientos") or []
        },
    )


def _address_to_dict(address: FiscalAddress) -> dict:
    return {
        "direccion": address.street,
        "numero_casa": address.house_number,
        "complemento_1": address.complement_1,
        "complemento_2": address.complement_2,
        "departamento": address.department_code,
        "descripcion_departamento": address.department_description,
        "distrito": address.district_code,
        "descripcion_distrito": address.district_description,
        "ciudad": address.city_code,
        "descripcion_ciudad": address.city_description,
        "telefono": address.phone,
        "email": address.email,
        "denominacion_sucursal": address.branch_name,
    }


def _address_from_dict(data: dict) -> FiscalAddress:
    return FiscalAddress(
        street=data["direccion"],
        house_number=str(data["numero_casa"]),
        complement_1=data.get("complemento_1"),
        complement_2=data.get("complemento_2"),
        department_code=int(data["departamento"]),
        department_description=data["descripcion_departamento"],
        district_code=_optional_int(data.get("distrito")),
        district_description=data.get("descripcion_distrito"),
        city_code=int(data["ciudad"]),
        city_description=data["descripcion_ciudad"],
        phone=data["telefono"],
        email=data["email"],
        branch_name=data.get("denominacion_sucursal"),
    )


def _optional_int(value) -> int | None:
    return None if value is None else int(value)
