"""Print KuDE values for people, from the exact text of the signed XML.

MT v150 §13.2 (p. 193): "No puede existir información en el KuDE que no
forme parte del formato del DE firmado (XML)", and §6.6 (p. 27): the
receiver checks "que la información presente en el KuDE coincide plenamente
con la información del DTE". So a printed number keeps every digit of its
XML literal, decimals included, and is never rounded; only the separators
change to the ones of the MT §13.4 examples ("110.000").
"""

from __future__ import annotations

import re

GUARANI = "PYG"

_ISO_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
# xs:decimal lexical form (sign, integer digits, "." and fraction digits),
# which is what tMontoBase, tdCantProSer and the exchange rates use.
_DECIMAL_LITERAL = re.compile(r"([+-]?)([0-9]*)(?:\.([0-9]*))?")


def format_decimal(literal: str | None) -> str:
    """Return a decimal XML literal with the separators of the MT examples.

    Every digit of the literal is kept, in the same order: "." groups the
    thousands of the integer part and "," replaces the decimal point, so
    ``9090.90909091`` prints ``9.090,90909091`` and ``120.50`` prints
    ``120,50``. A text that is not a decimal literal is returned unchanged.
    """

    text = (literal or "").strip()
    match = _DECIMAL_LITERAL.fullmatch(text)
    if match is None:
        return text
    sign, integer, fraction = match.groups()
    if not integer and not fraction:
        return text
    printed = f"{sign}{_group_thousands(integer)}"
    if fraction is None:
        return printed
    return f"{printed},{fraction}"


def format_kude_date(literal: str | None) -> str:
    """Return an ``AAAA-MM-DD`` XML date as ``DD-MM-AAAA``.

    NT 10 §1.11 (C008, dFeIniT): "Para el KuDE el formato de la fecha de
    inicio de vigencia debe contener los guiones separadores y representarse
    con el formato DD-MM-AAAA". Only C008 changes; any other text is
    returned unchanged.
    """

    text = (literal or "").strip()
    match = _ISO_DATE.fullmatch(text)
    if match is None:
        return text
    year, month, day = match.groups()
    return f"{day}-{month}-{year}"


def _group_thousands(digits: str) -> str:
    head = len(digits) % 3 or 3
    groups = [digits[:head]]
    groups.extend(digits[index : index + 3] for index in range(head, len(digits), 3))
    return ".".join(group for group in groups if group)
