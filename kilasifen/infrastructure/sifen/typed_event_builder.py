"""Typed SIFEN event XML builders (cancelacion + inutilizacion)."""

from __future__ import annotations

import re
from datetime import datetime
from xml.etree import ElementTree as ET

from lxml import etree
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

from kilasifen.engine.de.bindings.v150.evento_v150 import TgGroupGesEve
from kilasifen.engine.de.bindings.v150.ws_si_recep_evento_v150 import REnviEventoDe
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.engine.sdk.signer import get_pkcs12_signer
from kilasifen.engine.sdk.validation import validate_xml

SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
ET.register_namespace("", SIFEN_NS)

_WS_SERIALIZER = XmlSerializer(
    config=SerializerConfig(xml_declaration=True, encoding="UTF-8")
)


def build_signed_cancel_event_group_xml(
    *,
    cdc: str,
    motivo: str,
    signed_at: datetime,
    event_id: str,
    certificate_bytes: bytes,
    certificate_password: str,
) -> str:
    """Build and sign `gGroupGesEve` for cancelacion."""

    normalized_cdc = _normalize_cdc(cdc)
    normalized_motive = _normalize_motive(motivo)
    normalized_event_id = _normalize_event_id(event_id)
    signed_at_value = signed_at.strftime("%Y-%m-%dT%H:%M:%S")

    root = ET.Element(_tag("gGroupGesEve"))
    r_ges_eve = ET.SubElement(root, _tag("rGesEve"))
    r_eve = ET.SubElement(r_ges_eve, _tag("rEve"))
    r_eve.set("Id", normalized_event_id)
    ET.SubElement(r_eve, _tag("dFecFirma")).text = signed_at_value
    ET.SubElement(r_eve, _tag("dVerFor")).text = "150"

    g_group = ET.SubElement(r_eve, _tag("gGroupTiEvt"))
    cancel = ET.SubElement(g_group, _tag("rGeVeCan"))
    ET.SubElement(cancel, _tag("Id")).text = normalized_cdc
    ET.SubElement(cancel, _tag("mOtEve")).text = normalized_motive

    unsigned_xml = ET.tostring(root, encoding="unicode", xml_declaration=True)
    signed_xml = _sign_xml(
        unsigned_xml=unsigned_xml,
        event_id=normalized_event_id,
        certificate_bytes=certificate_bytes,
        certificate_password=certificate_password,
    )
    _validate_event_group_xml(signed_xml)
    return signed_xml


def build_signed_inutilization_event_group_xml(
    *,
    timbrado: str,
    i_tide: int,
    establishment: str,
    point: str,
    numero_desde: int,
    numero_hasta: int,
    motivo: str,
    signed_at: datetime,
    event_id: str,
    certificate_bytes: bytes,
    certificate_password: str,
    serie: str | None = None,
) -> str:
    """Build and sign `gGroupGesEve` for inutilizacion.

    ``serie`` is the optional ``dSerieNum`` added by NT 10 §1.7 (GEI009,
    ``[A-Z][A-Z]``, Evento_Types_v150.xsd ``tserieNum``), for a numbering
    restarted with a series after 9.999.999.
    """

    normalized_timbrado = _normalize_timbrado(timbrado)
    normalized_event_id = _normalize_event_id(event_id)
    normalized_est = _normalize_three_digits(establishment)
    normalized_point = _normalize_three_digits(point)
    if i_tide < 1 or i_tide > 8:
        raise SifenValidationError("events.inutilize.invalid_document_type")
    if numero_desde < 1 or numero_hasta < numero_desde:
        raise SifenValidationError("events.inutilize.invalid_range")
    normalized_from = f"{numero_desde:07d}"
    normalized_to = f"{numero_hasta:07d}"
    normalized_motive = _normalize_motive(motivo)
    signed_at_value = signed_at.strftime("%Y-%m-%dT%H:%M:%S")

    root = ET.Element(_tag("gGroupGesEve"))
    r_ges_eve = ET.SubElement(root, _tag("rGesEve"))
    r_eve = ET.SubElement(r_ges_eve, _tag("rEve"))
    r_eve.set("Id", normalized_event_id)
    ET.SubElement(r_eve, _tag("dFecFirma")).text = signed_at_value
    ET.SubElement(r_eve, _tag("dVerFor")).text = "150"

    g_group = ET.SubElement(r_eve, _tag("gGroupTiEvt"))
    inutilization = ET.SubElement(g_group, _tag("rGeVeInu"))
    ET.SubElement(inutilization, _tag("dNumTim")).text = normalized_timbrado
    ET.SubElement(inutilization, _tag("dEst")).text = normalized_est
    ET.SubElement(inutilization, _tag("dPunExp")).text = normalized_point
    ET.SubElement(inutilization, _tag("dNumIn")).text = normalized_from
    ET.SubElement(inutilization, _tag("dNumFin")).text = normalized_to
    ET.SubElement(inutilization, _tag("iTiDE")).text = str(i_tide)
    ET.SubElement(inutilization, _tag("mOtEve")).text = normalized_motive
    if serie is not None:
        ET.SubElement(inutilization, _tag("dSerieNum")).text = _normalize_serie(serie)

    unsigned_xml = ET.tostring(root, encoding="unicode", xml_declaration=True)
    signed_xml = _sign_xml(
        unsigned_xml=unsigned_xml,
        event_id=normalized_event_id,
        certificate_bytes=certificate_bytes,
        certificate_password=certificate_password,
    )
    _validate_event_group_xml(signed_xml)
    return signed_xml


def _sign_xml(
    *,
    unsigned_xml: str,
    event_id: str,
    certificate_bytes: bytes,
    certificate_password: str,
) -> str:
    signer = get_pkcs12_signer(certificate_bytes, certificate_password)
    signed = signer.sign(unsigned_xml, event_id)
    parser = etree.XMLParser(remove_blank_text=True)
    root = etree.fromstring(signed.encode("utf-8"), parser=parser)
    for element in root.iter():
        if element.text is not None and not element.text.strip():
            element.text = None
        if element.tail is not None and not element.tail.strip():
            element.tail = None
    compact = etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=False,
    ).decode("utf-8")
    if "ds:" in compact:
        raise SifenValidationError("events.signature.namespace_prefix_not_allowed")
    if "<!--" in compact:
        raise SifenValidationError("events.xml.comments_not_allowed")
    return compact


def _validate_event_group_xml(group_xml: str) -> None:
    """Validate event XML shape and WS schema compatibility."""

    try:
        group = TgGroupGesEve.from_xml(group_xml)
    except Exception as exc:  # pragma: no cover - parser error branch
        raise SifenValidationError("events.xml.invalid_structure") from exc

    request = REnviEventoDe(
        dId=1,
        dEvReg=REnviEventoDe.DEvReg(gGroupGesEve=group),
    )
    request_xml = _WS_SERIALIZER.render(request)
    errors = validate_xml(request_xml)
    if errors:
        raise SifenValidationError(f"events.xml.invalid_schema:{errors[0]}")


def _normalize_cdc(cdc: str) -> str:
    value = str(cdc).strip()
    if len(value) != 44 or not value.isdigit():
        raise SifenValidationError("events.cancel.invalid_cdc")
    return value


def _normalize_motive(motivo: str) -> str:
    value = str(motivo or "").strip()
    if len(value) < 5 or len(value) > 500:
        raise SifenValidationError("events.invalid_motivo_length")
    if any(char in value for char in ("\n", "\r", "\t")):
        raise SifenValidationError("events.invalid_motivo_whitespace")
    return value


def _normalize_event_id(event_id: str) -> str:
    value = "".join(char for char in str(event_id) if char.isdigit())
    if not value:
        raise SifenValidationError("events.invalid_event_id")
    if len(value) > 10:
        value = value[-10:]
    if int(value) <= 0:
        raise SifenValidationError("events.invalid_event_id")
    return value


def _normalize_timbrado(timbrado: str) -> str:
    value = str(timbrado).strip()
    if len(value) != 8 or not value.isdigit():
        raise SifenValidationError("events.inutilize.invalid_timbrado")
    return value


def _normalize_serie(serie: str) -> str:
    value = str(serie).strip()
    if not re.fullmatch(r"[A-Z]{2}", value):
        raise SifenValidationError("events.inutilize.invalid_serie")
    return value


def _normalize_three_digits(value: str) -> str:
    parsed = int(str(value).strip())
    if parsed < 0 or parsed > 999:
        raise SifenValidationError("events.inutilize.invalid_point_or_establishment")
    return f"{parsed:03d}"


def _tag(name: str) -> str:
    return f"{{{SIFEN_NS}}}{name}"
