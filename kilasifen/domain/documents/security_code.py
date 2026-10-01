"""Security code of a DE (``dCodSeg``, B004), part of its CDC.

MT v150 §10.3 (p. 57) and B004 (p. 62), XSD ``tiCodSe``: nine digits padded
with zeros, between 000000001 and 999999999, random and not sequential,
different for every DE, unrelated to the data of the DE or the emitter, and
different from ``dNumDoc``. The value is generated (or accepted from the
caller) once, when the document is created, and persisted with it: every
rebuild or retry of the same document must produce the same CDC (MT v150
§6.5; Decreto 872/2023 Art. 29).
"""

from __future__ import annotations

import secrets
from collections.abc import Callable

SECURITY_CODE_MIN = 1
SECURITY_CODE_MAX = 999_999_999


class InvalidSecurityCodeError(ValueError):
    """A security code that breaks MT v150 §10.3; ``code`` names the rule."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def generate_security_code(
    document_number: int,
    *,
    randbelow: Callable[[int], int] = secrets.randbelow,
) -> str:
    """Return a random nine-digit code from a CSPRNG, never equal to the number."""

    while True:
        value = randbelow(SECURITY_CODE_MAX) + SECURITY_CODE_MIN
        if value != document_number:
            return _format(value)


def normalize_security_code(value: object, *, document_number: int) -> str:
    """Validate a caller-supplied code and return it with nine digits."""

    text = str(value).strip()
    if not text.isdigit() or len(text) > 9:
        raise InvalidSecurityCodeError("documents.codigo_seguridad.invalid_format")
    number = int(text)
    if number < SECURITY_CODE_MIN:
        raise InvalidSecurityCodeError("documents.codigo_seguridad.zero")
    if number == document_number:
        raise InvalidSecurityCodeError("documents.codigo_seguridad.equals_numero")
    return _format(number)


def _format(value: int) -> str:
    return f"{value:09d}"
