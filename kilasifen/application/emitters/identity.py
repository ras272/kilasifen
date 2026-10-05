"""Validation of the fiscal identity an emitter is registered with.

Every value checked here ends up in ``gEmis`` and in the CDC, so a wrong one
makes SIFEN reject every document of the emitter. The rules come from the
official XSD types and the Manual Tecnico v150:

- ``dRucEm`` (D101): XSD ``tRuc``, 3-8 characters, ``[1-9][0-9]*[0-9A-D]?``.
- ``dDVEmi`` (D102): one digit, modulo 11 of the RUC (validation 1253).
- ``dNomEmi`` (D105): XSD ``tdNombre``, 4-255 characters.
- CSC: 32 alphanumeric characters (MT v150, control de versiones: "Se
  modifica el Codigo de Seguridad (CSC) a 32 digitos alfanumericos").
- ``IdCSC``: four digits (MT v150 §13.8.2, length 4), from 0001 to 9999.
"""

from __future__ import annotations

import re

from kilasifen.domain.common.errors import UnprocessableEntityError
from kilasifen.engine.sdk.fiscal import calculate_mod11_dv

_RUC_PATTERN = re.compile(r"^[1-9][0-9]*[0-9A-D]?$")
_DV_PATTERN = re.compile(r"^[0-9]$")
_CSC_PATTERN = re.compile(r"^[0-9A-Za-z]{32}$")
_CSC_ID_PATTERN = re.compile(r"^[0-9]{1,4}$")

RUC_MIN_LENGTH = 3
RUC_MAX_LENGTH = 8
LEGAL_NAME_MIN_LENGTH = 4
LEGAL_NAME_MAX_LENGTH = 255


def validate_tax_id(ruc: str, dv: str) -> None:
    """Reject a RUC outside ``tRuc`` or a DV that is not its modulo 11."""

    if not RUC_MIN_LENGTH <= len(ruc) <= RUC_MAX_LENGTH or not _RUC_PATTERN.match(
        ruc
    ):
        raise UnprocessableEntityError(
            "emitters.ruc_invalid",
            details={"pattern": _RUC_PATTERN.pattern, "length": "3-8"},
        )
    if not _DV_PATTERN.match(dv) or int(dv) != calculate_mod11_dv(ruc):
        raise UnprocessableEntityError("emitters.dv_mismatch")


def validate_legal_name(legal_name: str) -> None:
    """Reject a legal name outside the 4-255 characters of ``tdNombre``."""

    length = len(legal_name.strip())
    if not LEGAL_NAME_MIN_LENGTH <= length <= LEGAL_NAME_MAX_LENGTH:
        raise UnprocessableEntityError("emitters.legal_name_invalid")


def validate_csc(csc: str) -> None:
    """Reject a CSC that is not 32 alphanumeric characters."""

    if not _CSC_PATTERN.match(csc):
        raise UnprocessableEntityError("emitters.csc_invalid")


def normalize_csc_id(csc_id: str) -> str:
    """Return ``csc_id`` as the four digits ``IdCSC`` carries (``1`` -> ``0001``)."""

    stripped = csc_id.strip()
    if not _CSC_ID_PATTERN.match(stripped) or int(stripped) == 0:
        raise UnprocessableEntityError("emitters.csc_id_invalid")
    return stripped.zfill(4)
