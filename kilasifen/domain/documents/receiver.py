"""Receiver of a DE (``gDatRec``, D200-D224) under the rules in force.

One resolver serves the API (``422`` at creation) and the XML builder (local
validation failure in the worker), so both apply exactly the same rules. The
official catalogs are passed in, which keeps this module free of the engine.

Rules (MT v150 pp. 71-74 and §12.4 pp. 165-168, as modified by the NT):

- 1300 (NT 10 §2.1): a non-taxpayer (D201=2) is B2C (D202=2) or B2F (4).
- 1320 / 1301: B2F goes with a country other than PRY and every other
  operation with PRY; ``dDesPaisRe`` is the official name of the country.
- D201=1: ``iTiContRec`` (D205, 1302), ``dRucRec`` (D206, 1304, 3-8) and
  ``dDVRec`` (D207, "Obligatorio si existe el campo D206 / Segun algoritmo
  modulo 11", 1309) are mandatory; nothing is defaulted.
- D201=2: ``iTipIDRec``/``dDTipIDRec``/``dNumIDRec`` (D208-D210) always, B2F
  included (NT 23 §1.1, 1335). With D208=9 the real document type is given
  in 9-41 characters (XSD ``tdDtipDocRec``).
- Innominado (D208=5): only B2C (1333, NT 23); never in NC/ND/NR (1331,
  NT 23); ``dNumIDRec`` is "0" (NT 23 D210) and ``dNomRec`` "Sin Nombre"
  (D211). The 7.000.000 limit (1321, NT 24) needs the totals:
  :func:`innominado_limit_error`.
- Address: ``dDirRec`` is mandatory for C002=7 or D202=4 (1318) and optional
  otherwise; with an address ``dNumCasRec`` is mandatory (1330); with an
  address and D202 != 4 ``cDepRec`` and ``cCiuRec`` are mandatory, and with
  D202=4 they are not informed (NT 03). ``dDesDisRec`` goes with ``cDisRec``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

INNOMINADO = 5
OTHER_ID_TYPE = 9
INNOMINADO_NUMBER = "0"
INNOMINADO_NAME = "Sin Nombre"
#: NT 24 (from 2025-01-01): innominado only below 7.000.000 Gs (F014/F023).
INNOMINADO_LIMIT = Decimal("7000000")
#: D011 iTipTra 13 (Muestras medicas) is exempt from the innominado limit.
MEDICAL_SAMPLES_TRANSACTION = 13
#: C002 iTiDE that never accept an innominado receiver (1331): NC, ND, NR.
NO_INNOMINADO_DOCUMENT_TYPES = frozenset({5, 6, 7})
#: C002 iTiDE whose receiver address is always mandatory (1318): NR.
ADDRESS_REQUIRED_DOCUMENT_TYPES = frozenset({7})

ID_TYPE_DESCRIPTIONS = {
    1: "Cédula paraguaya",
    2: "Pasaporte",
    3: "Cédula extranjera",
    4: "Carnet de residencia",
    5: "Innominado",
    6: "Tarjeta Diplomática de exoneración fiscal",
}


class ReceiverRuleError(ValueError):
    """The receiver breaks a SIFEN rule; ``code`` names it."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ReceiverAddress:
    street: str | None = None  # D213 dDirRec
    house_number: str | None = None  # D218 dNumCasRec
    department_code: int | None = None  # D219 cDepRec
    department_description: str | None = None  # D220 dDesDepRec
    district_code: int | None = None  # D221 cDisRec
    district_description: str | None = None  # D222 dDesDisRec
    city_code: int | None = None  # D223 cCiuRec
    city_description: str | None = None  # D224 dDesCiuRec


@dataclass(frozen=True, slots=True)
class Receiver:
    nature: int  # D201 iNatRec
    operation_type: int  # D202 iTiOpe
    country_code: str  # D203 cPaisRec
    country_description: str  # D204 dDesPaisRe
    name: str  # D211 dNomRec
    taxpayer_type: int | None = None  # D205 iTiContRec
    ruc: str | None = None  # D206 dRucRec
    dv: str | None = None  # D207 dDVRec
    id_type: int | None = None  # D208 iTipIDRec
    id_type_description: str | None = None  # D209 dDTipIDRec
    id_number: str | None = None  # D210 dNumIDRec
    address: ReceiverAddress | None = None
    phone: str | None = None  # D214 dTelRec
    cellphone: str | None = None  # D215 dCelRec
    email: str | None = None  # D216 dEmailRec
    customer_code: str | None = None  # D217 dCodCliente

    @property
    def is_innominado(self) -> bool:
        return self.id_type == INNOMINADO


def resolve_receiver(
    cliente: dict,
    *,
    document_type: int,
    country_description: Callable[[str], str | None],
    department_description: Callable[[int], str | None],
    mod11_dv: Callable[[str], int],
) -> Receiver:
    """Validate the ``cliente`` payload and return the ``gDatRec`` data."""

    nature = _nature(cliente)
    operation_type = _operation_type(cliente)
    if nature == 2 and operation_type not in (2, 4):
        raise ReceiverRuleError("documents.cliente.tipo_operacion_not_allowed")
    country_code, country_name = _country(cliente, operation_type, country_description)

    fields: dict = {}
    if nature == 1:
        fields.update(_taxpayer_identity(cliente, mod11_dv))
    else:
        fields.update(_non_taxpayer_identity(cliente, operation_type, document_type))
    innominado = fields.get("id_type") == INNOMINADO
    return Receiver(
        nature=nature,
        operation_type=operation_type,
        country_code=country_code,
        country_description=country_name,
        name=INNOMINADO_NAME if innominado else _name(cliente),
        address=_address(
            cliente, operation_type, document_type, department_description
        ),
        phone=_text(cliente.get("telefono")),
        cellphone=_text(cliente.get("celular")),
        email=_text(cliente.get("email")),
        customer_code=_text(cliente.get("codigo_cliente")),
        **fields,
    )


def innominado_limit_error(
    receiver: Receiver,
    *,
    transaction_type: int | None,
    currency: str,
    total_operation: Decimal,
    total_guaranies: Decimal | None,
) -> str | None:
    """1321 (NT 24): innominado only below 7.000.000 Gs, except D011=13."""

    if not receiver.is_innominado:
        return None
    if transaction_type == MEDICAL_SAMPLES_TRANSACTION:
        return None
    total = total_operation if currency == "PYG" else total_guaranies
    if total is not None and total >= INNOMINADO_LIMIT:
        return "documents.cliente.innominado_over_limit"
    return None


def _nature(cliente: dict) -> int:
    explicit = _int(_first(cliente, "naturaleza", "iNatRec"), "naturaleza")
    if explicit is None:
        return 1 if _text(cliente.get("ruc")) else 2
    if explicit not in (1, 2):
        raise ReceiverRuleError("documents.cliente.naturaleza_invalid")
    return explicit


def _operation_type(cliente: dict) -> int:
    explicit = _int(_first(cliente, "tipo_operacion", "iTiOpe"), "tipo_operacion")
    if explicit is None:
        return 1 if _text(cliente.get("ruc")) else 2
    if explicit not in (1, 2, 3, 4):
        raise ReceiverRuleError("documents.cliente.tipo_operacion_invalid")
    return explicit


def _country(
    cliente: dict,
    operation_type: int,
    country_description: Callable[[str], str | None],
) -> tuple[str, str]:
    code = (_text(_first(cliente, "pais_codigo", "cPaisRec")) or "PRY").upper()
    if (operation_type == 4) == (code == "PRY"):
        raise ReceiverRuleError("documents.cliente.pais_inconsistent_with_operation")
    official = country_description(code)
    if official is None:
        raise ReceiverRuleError("documents.cliente.pais_unknown")
    given = _text(_first(cliente, "pais_descripcion", "dDesPaisRe"))
    if given is not None and given.casefold() != official.casefold():
        raise ReceiverRuleError("documents.cliente.pais_descripcion_mismatch")
    return code, official


def _taxpayer_identity(cliente: dict, mod11_dv: Callable[[str], int]) -> dict:
    taxpayer_type = _int(
        _first(cliente, "tipo_contribuyente", "iTiContRec"), "tipo_contribuyente"
    )
    if taxpayer_type is None:
        raise ReceiverRuleError("documents.cliente.tipo_contribuyente_required")
    if taxpayer_type not in (1, 2):
        raise ReceiverRuleError("documents.cliente.tipo_contribuyente_invalid")
    raw_ruc = _text(cliente.get("ruc"))
    if raw_ruc is None:
        raise ReceiverRuleError("documents.cliente.ruc_required")
    ruc, ruc_dv = raw_ruc.split("-", 1) if "-" in raw_ruc else (raw_ruc, None)
    ruc = ruc.strip()
    dv = _text(ruc_dv) or _text(cliente.get("dv"))
    if not 3 <= len(ruc) <= 8:
        raise ReceiverRuleError("documents.cliente.ruc_invalid")
    if dv is None:
        raise ReceiverRuleError("documents.cliente.dv_required")
    if not dv.isdigit() or int(dv) != mod11_dv(ruc):
        raise ReceiverRuleError("documents.cliente.dv_mismatch")
    return {"taxpayer_type": taxpayer_type, "ruc": ruc, "dv": dv}


def _non_taxpayer_identity(
    cliente: dict, operation_type: int, document_type: int
) -> dict:
    id_type = _int(
        _first(cliente, "tipo_documento_identidad", "iTipIDRec", "tipo_documento"),
        "tipo_documento_identidad",
    )
    if id_type is None:
        raise ReceiverRuleError("documents.cliente.tipo_documento_identidad_required")
    if id_type not in (*ID_TYPE_DESCRIPTIONS, OTHER_ID_TYPE):
        raise ReceiverRuleError("documents.cliente.tipo_documento_identidad_invalid")
    if id_type == INNOMINADO:
        if operation_type != 2:
            raise ReceiverRuleError("documents.cliente.innominado_requires_b2c")
        if document_type in NO_INNOMINADO_DOCUMENT_TYPES:
            raise ReceiverRuleError("documents.cliente.innominado_not_allowed")
        return {
            "id_type": id_type,
            "id_type_description": ID_TYPE_DESCRIPTIONS[id_type],
            "id_number": INNOMINADO_NUMBER,
        }
    if id_type == OTHER_ID_TYPE:
        description = _text(
            _first(cliente, "descripcion_tipo_documento", "dDTipIDRec")
        )
        if description is None or not 9 <= len(description) <= 41:
            raise ReceiverRuleError(
                "documents.cliente.descripcion_tipo_documento_required"
            )
    else:
        description = ID_TYPE_DESCRIPTIONS[id_type]
    number = _text(
        _first(cliente, "numero_documento_identidad", "dNumIDRec", "numero_documento")
    )
    if number is None:
        raise ReceiverRuleError("documents.cliente.numero_documento_identidad_required")
    return {"id_type": id_type, "id_type_description": description, "id_number": number}


def _name(cliente: dict) -> str:
    name = _text(_first(cliente, "razon_social", "razonSocial", "nombre", "dNomRec"))
    if name is None:
        raise ReceiverRuleError("documents.cliente.nombre_required")
    if not 4 <= len(name) <= 255:
        raise ReceiverRuleError("documents.cliente.nombre_invalid")
    return name


def _address(
    cliente: dict,
    operation_type: int,
    document_type: int,
    department_description: Callable[[int], str | None],
) -> ReceiverAddress | None:
    street = _text(_first(cliente, "direccion", "dDirRec"))
    house_number = _text(_first(cliente, "numero_casa", "dNumCasRec"))
    department = _int(cliente.get("departamento"), "departamento")
    district = _int(cliente.get("distrito"), "distrito")
    city = _int(cliente.get("ciudad"), "ciudad")
    district_description = _text(cliente.get("descripcion_distrito"))
    city_description = _text(cliente.get("descripcion_ciudad"))
    given_department = _text(cliente.get("descripcion_departamento"))
    has_location = any(
        value is not None
        for value in (
            department,
            district,
            city,
            given_department,
            district_description,
            city_description,
        )
    )

    if street is None and (
        operation_type == 4 or document_type in ADDRESS_REQUIRED_DOCUMENT_TYPES
    ):
        raise ReceiverRuleError("documents.cliente.direccion_required")  # 1318
    if street is not None and house_number is None:
        raise ReceiverRuleError("documents.cliente.numero_casa_required")  # 1330
    if operation_type == 4 and has_location:
        # NT 03: cDepRec and cCiuRec are not informed for B2F.
        raise ReceiverRuleError("documents.cliente.ubicacion_not_allowed_for_b2f")
    if street is not None and operation_type != 4 and None in (department, city):
        # NT 03: mandatory when there is an address and D202 != 4.
        raise ReceiverRuleError("documents.cliente.departamento_ciudad_required")
    if street is None and house_number is None and not has_location:
        return None

    department_description_text = None
    if department is not None:
        department_description_text = department_description(department)
        if department_description_text is None:
            raise ReceiverRuleError("documents.cliente.departamento_unknown")
        if (
            given_department is not None
            and given_department.upper() != department_description_text
        ):
            raise ReceiverRuleError(
                "documents.cliente.descripcion_departamento_mismatch"
            )
    if (city is None) != (city_description is None):
        raise ReceiverRuleError("documents.cliente.ciudad_incomplete")
    if (district is None) != (district_description is None):
        raise ReceiverRuleError("documents.cliente.distrito_incomplete")
    return ReceiverAddress(
        street=street,
        house_number=house_number,
        department_code=department,
        department_description=department_description_text,
        district_code=district,
        district_description=district_description,
        city_code=city,
        city_description=city_description,
    )


def _first(data: dict, *keys: str):
    for key in keys:
        if data.get(key) is not None:
            return data[key]
    return None


def _int(value, field: str) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return int(str(value).strip())
    except ValueError as exc:
        raise ReceiverRuleError(f"documents.cliente.{field}_invalid") from exc


def _text(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None
