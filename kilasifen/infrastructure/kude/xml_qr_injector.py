"""Inject the real SIFEN QR URL into a signed DE XML.

The ``gCamFuFD/dCarQR`` element sits outside the signed ``<DE>`` element,
so its text can be replaced post-sign without invalidating the signature.
This module recomputes the QR URL with the actual ``DigestValue`` from the
signature plus the emitter CSC, then substitutes it in the original XML
via string replacement (preserving signxml's exact byte serialization).
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from xml.etree import ElementTree as ET

from kilasifen.domain.emitters.models import Emitter
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.infrastructure.kude.qr_generator import build_sifen_qr_url

_SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
_DSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
_DCARQR_PATTERN = re.compile(r"<dCarQR>([^<]*)</dCarQR>")


def apply_real_qr_to_signed_xml(signed_xml: str, *, emitter: Emitter) -> str:
    """Replace the placeholder dCarQR with the real SIFEN QR URL.

    Returns the updated XML string. Raises SifenValidationError when the
    emitter has no CSC or the XML structure does not match the SIFEN format.
    """

    if not emitter.csc or not emitter.csc_id:
        raise SifenValidationError("emitters.csc_required")

    qr_url = compute_qr_url_from_signed_xml(signed_xml, emitter=emitter)
    qr_url_xml_escaped = qr_url.replace("&", "&amp;")

    if not _DCARQR_PATTERN.search(signed_xml):
        raise SifenValidationError("documents.qr.dcarqr_element_missing")

    return _DCARQR_PATTERN.sub(
        f"<dCarQR>{qr_url_xml_escaped}</dCarQR>",
        signed_xml,
        count=1,
    )


def compute_qr_url_from_signed_xml(signed_xml: str, *, emitter: Emitter) -> str:
    """Compute the SIFEN QR URL for a signed XML using emitter credentials."""

    if not emitter.csc or not emitter.csc_id:
        raise SifenValidationError("emitters.csc_required")

    root = ET.fromstring(signed_xml.encode("utf-8"))
    de = root.find(f"{{{_SIFEN_NS}}}DE")
    if de is None:
        raise SifenValidationError("documents.qr.signed_xml_missing_de")
    cdc = de.attrib.get("Id")
    if not cdc:
        raise SifenValidationError("documents.qr.cdc_missing")

    fecha_text = _find_text(de, [f"{{{_SIFEN_NS}}}gDatGralOpe", f"{{{_SIFEN_NS}}}dFeEmiDE"])
    if not fecha_text:
        raise SifenValidationError("documents.qr.fecha_emision_missing")

    receptor = _resolve_receptor_identifier(de)
    total_general, total_iva = _resolve_totals(de)
    items_count = _count_items(de)
    digest_value = _extract_digest_value(root)

    ambiente = "produccion" if emitter.tax_environment != "test" else "test"
    return build_sifen_qr_url(
        cdc=cdc,
        fecha_emision=_parse_iso_datetime(fecha_text),
        rec_identifier=receptor,
        total_general=total_general,
        total_iva=total_iva,
        cantidad_items=items_count,
        digest_value=digest_value,
        csc=emitter.csc,
        id_csc=emitter.csc_id,
        ambiente=ambiente,
    )


def _find_text(parent: ET.Element, path: list[str]) -> str | None:
    node = parent
    for tag in path:
        found = node.find(tag)
        if found is None:
            return None
        node = found
    return (node.text or "").strip() or None


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _resolve_receptor_identifier(de: ET.Element) -> str:
    rec = de.find(
        f"{{{_SIFEN_NS}}}gDatGralOpe/{{{_SIFEN_NS}}}gDatRec"
    )
    if rec is None:
        return "0"
    nat = _find_child_text(rec, "iNatRec")
    if nat == "1":
        ruc = _find_child_text(rec, "dRucRec")
        if ruc:
            return ruc
    doc = _find_child_text(rec, "dNumIDRec")
    return doc or "0"


def _resolve_totals(de: ET.Element) -> tuple[Decimal | None, Decimal | None]:
    tot = de.find(f"{{{_SIFEN_NS}}}gTotSub")
    if tot is None:
        return None, None
    total_general = _decimal_or_none(_find_child_text(tot, "dTotGralOpe"))
    total_iva = _decimal_or_none(_find_child_text(tot, "dTotIVA"))
    return total_general, total_iva


def _count_items(de: ET.Element) -> int:
    dtip = de.find(f"{{{_SIFEN_NS}}}gDtipDE")
    if dtip is None:
        return 0
    return len(dtip.findall(f"{{{_SIFEN_NS}}}gCamItem"))


def _extract_digest_value(root: ET.Element) -> str:
    digest = root.find(
        f"{{{_DSIG_NS}}}Signature"
        f"/{{{_DSIG_NS}}}SignedInfo"
        f"/{{{_DSIG_NS}}}Reference"
        f"/{{{_DSIG_NS}}}DigestValue"
    )
    if digest is None or not (digest.text or "").strip():
        raise SifenValidationError("documents.qr.digest_value_missing")
    return digest.text.strip()


def _find_child_text(parent: ET.Element, local_name: str) -> str | None:
    child = parent.find(f"{{{_SIFEN_NS}}}{local_name}")
    if child is None:
        return None
    return (child.text or "").strip() or None


def _decimal_or_none(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except Exception:  # pragma: no cover - defensive
        return None
