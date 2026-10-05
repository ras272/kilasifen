"""Emitter identity a typed document may repeat but never change.

``dRucEm``, ``dDVEmi``, ``dNomEmi`` and ``iTipCont`` come only from the
registered emitter: the same values feed the XML and the CDC (MT v150 A002,
validation 1000), the RUC must be the one of the signing certificate (D101,
0142) and of the timbrado (C004, 1101). A typed payload may still carry them
in ``emisor`` or ``tipo_contribuyente``; they are accepted only when they
match the emitter.
"""

from __future__ import annotations


def find_emitter_identity_mismatch(
    typed_payload: dict,
    *,
    ruc: str,
    dv: str,
    legal_name: str,
    taxpayer_type: int,
) -> str | None:
    """Return the first payload field that contradicts the emitter, or ``None``."""

    declared_type = typed_payload.get("tipo_contribuyente")
    if declared_type is not None and str(declared_type).strip() != str(taxpayer_type):
        return "tipo_contribuyente"

    emisor = typed_payload.get("emisor")
    if not isinstance(emisor, dict):
        return None

    declared_ruc, ruc_dv = _split_ruc(emisor.get("ruc"))
    if declared_ruc is not None and declared_ruc != ruc:
        return "emisor.ruc"
    if ruc_dv is not None and ruc_dv != dv:
        return "emisor.ruc"
    declared_dv = _text(emisor.get("dv"))
    if declared_dv is not None and declared_dv != dv:
        return "emisor.dv"

    for key in ("razon_social", "nombre"):
        declared_name = _text(emisor.get(key))
        if declared_name is not None and declared_name.casefold() != (
            legal_name.strip().casefold()
        ):
            return f"emisor.{key}"
    return None


def _split_ruc(value) -> tuple[str | None, str | None]:
    text = _text(value)
    if text is None:
        return None, None
    if "-" in text:
        base, dv = text.split("-", 1)
        return base.strip(), dv.strip()
    return text, None


def _text(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None
