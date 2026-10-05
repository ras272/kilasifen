"""Fictional emitter fiscal profiles for tests, examples and golden scenarios.

Every value is invented: none belongs to a real taxpayer. The department code
and description come from the official catalog (``Departamentos_v141.xsd``)
so the profile passes the same validation as a real one.
"""

from __future__ import annotations

from copy import deepcopy

from kilasifen.domain.emitters.fiscal_profile import (
    EmitterFiscalProfile,
    fiscal_profile_from_dict,
)

FICTIONAL_FISCAL_PROFILE: dict = {
    "tipo_contribuyente": 2,
    "tipo_regimen": None,
    "nombre_fantasia": None,
    "actividades_economicas": [
        {"codigo": "62010", "descripcion": "ACTIVIDADES DE PROGRAMACION INFORMATICA"}
    ],
    "domicilio": {
        "direccion": "CALLE FICTICIA",
        "numero_casa": "123",
        "complemento_1": None,
        "complemento_2": None,
        "departamento": 1,
        "descripcion_departamento": "CAPITAL",
        "distrito": None,
        "descripcion_distrito": None,
        "ciudad": 1,
        "descripcion_ciudad": "ASUNCION (DISTRITO)",
        "telefono": "021123456",
        "email": "facturacion@example.com",
        "denominacion_sucursal": None,
    },
    "establecimientos": [],
}


def fictional_fiscal_profile_payload() -> dict:
    """Return a fresh copy of the fictional profile in API form."""

    return deepcopy(FICTIONAL_FISCAL_PROFILE)


def fictional_fiscal_profile() -> EmitterFiscalProfile:
    """Return the fictional profile as a domain object."""

    return fiscal_profile_from_dict(fictional_fiscal_profile_payload())
