"""Fiscal event submission adapters backed by pysifen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from xml.etree import ElementTree as ET

from lxml import etree
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

from pysifen import PRODUCCION, TEST
from pysifen.sdk.errors import SifenValidationError
from pysifen.transmissao.evento import TransmissaoEvento
from pysifen.transmissao.evento import _generate_id

from kilasifen.domain.certificates.models import Certificate
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.events.models import Event


@dataclass(slots=True)
class EventSubmissionOutcome:
    """Normalized result from one event submission attempt."""

    generated_xml: str | None
    signed_xml: str | None
    request_xml: str
    response_raw: str
    status: str
    result_code: str | None
    result_message: str | None
    protocol: str | None


class EventSubmissionGateway(Protocol):
    """Contract for event submission adapters."""

    def submit_event(
        self,
        *,
        event: Event,
        emitter: Emitter,
        certificate: Certificate,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> EventSubmissionOutcome:
        """Submit one event and return normalized artifacts."""


class PysifenEventGateway:
    """Concrete event submission adapter backed by pysifen."""

    def __init__(self):
        self.serializer = XmlSerializer(
            config=SerializerConfig(xml_declaration=True, encoding="UTF-8")
        )

    def submit_event(
        self,
        *,
        event: Event,
        emitter: Emitter,
        certificate: Certificate,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> EventSubmissionOutcome:
        del certificate
        event_xml = _extract_event_xml(event.input_payload)
        request_xml = _build_enviar_evento_request_xml(
            d_id=_generate_id(),
            event_group_xml=event_xml,
        )

        ambiente = TEST if emitter.tax_environment == "test" else PRODUCCION
        response_raw = _submit_event_raw(
            ambiente=ambiente,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
            request_xml=request_xml,
        )
        response = response_raw

        result_code, result_message, status, protocol = _normalize_response(response)

        return EventSubmissionOutcome(
            generated_xml=event_xml,
            signed_xml=None,
            request_xml=request_xml,
            response_raw=response_raw,
            status=status,
            result_code=result_code,
            result_message=result_message,
            protocol=protocol,
        )


def _extract_event_xml(input_payload: dict | None) -> str:
    if not input_payload or not isinstance(input_payload, dict):
        raise SifenValidationError("event payload must include event_xml")
    event_xml = input_payload.get("event_xml")
    if not event_xml or not isinstance(event_xml, str):
        raise SifenValidationError("event payload must include event_xml")
    return event_xml


def _normalize_response(response) -> tuple[str | None, str | None, str, str | None]:
    if isinstance(response, str):
        return _normalize_response_raw_xml(response)

    result_code = None
    result_message = None
    status = "submitted"
    protocol = None

    g_res_proc = []
    if getattr(response, "gResProcEVe", None):
        first_group = response.gResProcEVe[0]
        g_res_proc = getattr(first_group, "gResProc", [])
        protocol = str(getattr(first_group, "dProtAut", "") or "").strip() or None
        if getattr(first_group, "dEstRes", None):
            raw_status = str(first_group.dEstRes).strip().lower()
            status = "approved" if "aprob" in raw_status else "rejected"

    if g_res_proc:
        result_code = getattr(g_res_proc[0], "dCodRes", None)
        result_message = getattr(g_res_proc[0], "dMsgRes", None)

    if result_code in {"0260", "0300"}:
        status = "approved"
    elif result_code is not None and status != "approved":
        status = "rejected"

    return result_code, result_message, status, protocol


def _submit_event_raw(
    *,
    ambiente: int,
    certificate_bytes: bytes,
    certificate_password: str,
    request_xml: str,
) -> str:
    with TransmissaoEvento(
        ambiente=ambiente,
        pkcs12_data=certificate_bytes,
        pkcs12_password=certificate_password,
    ) as transmissao:
        response_raw = transmissao._send_raw_xml("evento", request_xml)
    return response_raw.decode("utf-8")


def _build_enviar_evento_request_xml(*, d_id: int, event_group_xml: str) -> str:
    ns = "http://ekuatia.set.gov.py/sifen/xsd"
    parser = etree.XMLParser(remove_blank_text=True)

    request_root = etree.Element(f"{{{ns}}}rEnviEventoDe", nsmap={None: ns})
    d_id_el = etree.SubElement(request_root, f"{{{ns}}}dId")
    d_id_el.text = str(d_id)
    d_ev_reg = etree.SubElement(request_root, f"{{{ns}}}dEvReg")

    normalized_group_xml = _strip_xml_declaration(event_group_xml)
    group_root = etree.fromstring(normalized_group_xml.encode("utf-8"), parser=parser)
    d_ev_reg.append(group_root)

    return etree.tostring(
        request_root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=False,
    ).decode("utf-8")


def _strip_xml_declaration(value: str) -> str:
    text = str(value).strip()
    if text.startswith("<?xml"):
        closing = text.find("?>")
        if closing != -1:
            text = text[closing + 2 :].lstrip()
    return text


def _normalize_response_raw_xml(
    response_raw: str,
) -> tuple[str | None, str | None, str, str | None]:
    try:
        root = ET.fromstring(response_raw.encode("utf-8"))
    except ET.ParseError as exc:
        raise SifenValidationError("events.response.invalid_xml") from exc

    result_code = _find_text(root, "dCodRes")
    result_message = _find_text(root, "dMsgRes")
    protocol = _find_text(root, "dProtAut")
    status_text = (_find_text(root, "dEstRes") or "").strip().lower()

    status = "submitted"
    if "aprob" in status_text:
        status = "approved"
    elif "rechaz" in status_text:
        status = "rejected"

    if result_code in {"0260", "0300"}:
        status = "approved"
    elif result_code is not None and status != "approved":
        status = "rejected"

    return result_code, result_message, status, protocol


def _find_text(root: ET.Element, local_name: str) -> str | None:
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != local_name:
            continue
        value = (element.text or "").strip()
        if value:
            return value
    return None
