"""Validation of the emitter fiscal profile against the official formats.

The API schema checks lengths and patterns; this module holds the rules that
need the official catalogs or span several fields, and runs for every caller
of :class:`~kilasifen.application.emitters.service.EmitterService`:

- ``iTipCont`` (D103) is 1 or 2; ``cTipReg`` (D104) is 1-8 (XSD ``tcTipReg``).
- 1 to 9 ``gActEco`` groups (D130, ``DE_v150.xsd`` ``maxOccurs="9"``).
- ``cDepEmi``/``dDesDepEmi`` (D111/D112) come from ``Departamentos_v141.xsd``
  (validation 1254); the description is stored with its official spelling.
- ``dDesDisEmi`` (D114) is required when ``cDisEmi`` (D113) is present (1256).
- Establishment overrides use a three-digit ``dEst`` code (C005), once each.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import NoReturn

from kilasifen.domain.common.errors import UnprocessableEntityError
from kilasifen.domain.emitters.fiscal_profile import (
    EmitterFiscalProfile,
    FiscalAddress,
)
from kilasifen.engine.sdk.catalogos import descripcion_departamento

MAX_ECONOMIC_ACTIVITIES = 9
_ESTABLISHMENT_PATTERN = re.compile(r"^[0-9]{3}$")


def normalize_fiscal_profile(profile: EmitterFiscalProfile) -> EmitterFiscalProfile:
    """Validate ``profile`` and return it with official catalog descriptions."""

    if profile.taxpayer_type not in (1, 2):
        _invalid("tipo_contribuyente", "must be 1 or 2")
    if profile.regime_type is not None and not 1 <= profile.regime_type <= 8:
        _invalid("tipo_regimen", "must be between 1 and 8")
    if not 1 <= len(profile.activities) <= MAX_ECONOMIC_ACTIVITIES:
        _invalid("actividades_economicas", "must have between 1 and 9 items")
    for code in profile.establishments:
        if not _ESTABLISHMENT_PATTERN.match(code):
            _invalid("establecimientos", "establishment codes have three digits")
    return replace(
        profile,
        address=_normalize_address(profile.address, field="domicilio"),
        establishments={
            code: _normalize_address(address, field=f"establecimientos.{code}")
            for code, address in profile.establishments.items()
        },
    )


def _normalize_address(address: FiscalAddress, *, field: str) -> FiscalAddress:
    official = descripcion_departamento(address.department_code)
    if official is None:
        _invalid(f"{field}.departamento", "unknown department code")
    given = address.department_description
    if given and given.strip().upper() != official:
        _invalid(f"{field}.descripcion_departamento", "does not match the code")
    has_district_code = address.district_code is not None
    if has_district_code != bool(address.district_description):
        _invalid(f"{field}.distrito", "code and description go together")
    return replace(address, department_description=official)


def _invalid(field: str, reason: str) -> NoReturn:
    raise UnprocessableEntityError(
        "emitters.fiscal_profile_invalid",
        details={"field": field, "reason": reason},
    )
