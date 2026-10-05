"""Print KuDE values for people, from the exact text of the signed XML.

Only the printed text changes: the XML, and the JSON KuDE data, keep the
literal values (amounts with up to 8 decimals, XSD tMontoBase and NT 13).
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

GUARANI = "PYG"

_ISO_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
# Paraguayan convention, as in the MT v150 §13.4 examples ("110.000"):
# "." groups thousands and "," separates decimals.
_LOCAL_SEPARATORS = str.maketrans({",": ".", ".": ","})


def format_amount(literal: str | None, currency: str | None) -> str:
    """Return an XML amount rounded for reading.

    Guaranies print without decimals and any other currency with two,
    rounded half up from the exact XML value. A text that is not a decimal
    number is returned unchanged.
    """

    text = (literal or "").strip()
    if not text:
        return ""
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return text
    if not amount.is_finite():
        return text
    places = 0 if (currency or GUARANI).strip().upper() == GUARANI else 2
    rounded = amount.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return f"{rounded:,.{places}f}".translate(_LOCAL_SEPARATORS)


def format_kude_date(literal: str | None) -> str:
    """Return an ``AAAA-MM-DD`` XML date as ``DD-MM-AAAA``.

    NT 10 §1.11 (C008, dFeIniT): "Para el KuDE el formato de la fecha de
    inicio de vigencia debe contener los guiones separadores y representarse
    con el formato DD-MM-AAAA". Any other text is returned unchanged.
    """

    text = (literal or "").strip()
    match = _ISO_DATE.fullmatch(text)
    if match is None:
        return text
    year, month, day = match.groups()
    return f"{day}-{month}-{year}"
