"""Fiscal event submission adapters backed by kilasifen.engine.

Like documents, an event is submitted in two steps so the platform can make
the exact request durable before it travels: ``prepare_event`` wraps the
signed ``gGroupGesEve`` in an ``rEnviEventoDe`` with its real ``dId`` and
verifies the signature locally, without network; ``submit_prepared`` sends
that text unchanged and normalizes the answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from xml.etree import ElementTree as ET

from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
from signxml import InvalidSignature, XMLVerifier
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.events.models import Event
from kilasifen.engine import PRODUCCION, TEST
from kilasifen.engine.sdk.errors import (
    SifenUnexpectedResponseError,
    SifenValidationError,
)
from kilasifen.engine.transmision.evento import TransmisionEvento, _generate_id

#: Root element of the answer of the event reception service.
_EVENT_RESPONSE_ROOT = "rRetEnviEventoDe"


@dataclass(frozen=True, slots=True)
class PreparedEventSubmission:
    """Signed event group and the exact ``rEnviEventoDe`` that carries it."""

    signed_xml: str
    request_xml: str


@dataclass(slots=True)
class EventSubmissionOutcome:
    """Normalized SIFEN answer to one event submission."""

    response_raw: str
    status: str
    result_code: str | None
    result_message: str | None
    protocol: str | None


class EventSubmissionGateway(Protocol):
    """Contract for event submission adapters."""

    def prepare_event(
        self,
        *,
        event: Event,
        emitter: Emitter,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> PreparedEventSubmission:
        """Wrap and verify one signed event without contacting SIFEN.

        Raises:
            SifenValidationError: if the event cannot be sent as is.
        """

    def submit_prepared(
        self,
        *,
        request_xml: str,
        emitter: Emitter,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> EventSubmissionOutcome:
        """Send a prepared ``rEnviEventoDe`` unchanged and normalize the answer.

        Any exception other than
        :class:`~kilasifen.engine.sdk.errors.SifenRequestNotSentError` leaves
        the outcome unknown: SIFEN may have processed the request.
        """


class KilaSifenEventGateway:
    """Concrete event submission adapter backed by kilasifen.engine."""

    def __init__(self, deployment_environment: str = "test"):
        self.deployment_environment = deployment_environment
        self.serializer = XmlSerializer(
            config=SerializerConfig(xml_declaration=True, encoding="UTF-8")
        )

    def prepare_event(
        self,
        *,
        event: Event,
        emitter: Emitter,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> PreparedEventSubmission:
        if emitter.tax_environment != self.deployment_environment:
            raise SifenValidationError(
                "Emitter tax environment does not match this deployment"
            )
        event_xml = _extract_event_xml(event.input_payload)
        request_xml = _build_enviar_evento_request_xml(
            d_id=_generate_id(),
            event_group_xml=event_xml,
        )
        _verify_event_signature_locally(
            request_xml=request_xml,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
        )
        return PreparedEventSubmission(signed_xml=event_xml, request_xml=request_xml)

    def submit_prepared(
        self,
        *,
        request_xml: str,
        emitter: Emitter,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> EventSubmissionOutcome:
        ambiente = TEST if emitter.tax_environment == "test" else PRODUCCION
        response_raw = _submit_event_raw(
            ambiente=ambiente,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
            request_xml=request_xml,
        )
        result_code, result_message, status, protocol = _normalize_response(
            response_raw
        )
        return EventSubmissionOutcome(
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

    if result_code in {"0260", "0300", "0600"}:
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
    with TransmisionEvento(
        ambiente=ambiente,
        pkcs12_data=certificate_bytes,
        pkcs12_password=certificate_password,
    ) as transmision:
        response_raw = transmision._send_raw_xml("evento", request_xml)
    return response_raw.decode("utf-8")


def _build_enviar_evento_request_xml(*, d_id: int, event_group_xml: str) -> str:
    normalized_group_xml = _strip_xml_declaration(event_group_xml)
    group_with_schema = _inject_event_schema_location(normalized_group_xml)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rEnviEventoDe xmlns="http://ekuatia.set.gov.py/sifen/xsd">'
        f"<dId>{d_id}</dId>"
        f"<dEvReg>{group_with_schema}</dEvReg>"
        "</rEnviEventoDe>"
    )


def _strip_xml_declaration(value: str) -> str:
    text = str(value).strip()
    if text.startswith("<?xml"):
        closing = text.find("?>")
        if closing != -1:
            text = text[closing + 2 :].lstrip()
    return text


def _inject_event_schema_location(event_group_xml: str) -> str:
    root_tag = '<gGroupGesEve xmlns="http://ekuatia.set.gov.py/sifen/xsd"'
    replacement = (
        '<gGroupGesEve xmlns="http://ekuatia.set.gov.py/sifen/xsd" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://ekuatia.set.gov.py/sifen/xsd '
        'siRecepEvento_v150.xsd"'
    )
    if "xsi:schemaLocation=" in event_group_xml:
        return event_group_xml
    if root_tag not in event_group_xml:
        raise SifenValidationError("events.xml.invalid_root")
    return event_group_xml.replace(root_tag, replacement, 1)


def _verify_event_signature_locally(
    *,
    request_xml: str,
    certificate_bytes: bytes,
    certificate_password: str,
) -> None:
    event_group_xml = _extract_wrapped_event_group_xml(request_xml)
    cert_pem = _extract_public_certificate_pem(
        certificate_bytes=certificate_bytes,
        certificate_password=certificate_password,
    )
    try:
        XMLVerifier().verify(
            event_group_xml.encode("utf-8"),
            x509_cert=cert_pem,
            id_attribute="Id",
        )
    except InvalidSignature as exc:
        raise SifenValidationError(
            "events.signature.local_verification_failed"
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive verifier fallback
        raise SifenValidationError(
            "events.signature.local_verification_failed"
        ) from exc


def _extract_public_certificate_pem(
    *,
    certificate_bytes: bytes,
    certificate_password: str,
) -> bytes:
    _, certificate, _ = pkcs12.load_key_and_certificates(
        certificate_bytes,
        certificate_password.encode("utf-8"),
    )
    if certificate is None:
        raise SifenValidationError("events.signature.local_verification_failed")
    return certificate.public_bytes(Encoding.PEM)


def _extract_wrapped_event_group_xml(request_xml: str) -> str:
    start_tag = "<gGroupGesEve"
    end_tag = "</gGroupGesEve>"
    start = request_xml.find(start_tag)
    end = request_xml.find(end_tag)
    if start == -1 or end == -1:
        raise SifenValidationError("events.xml.invalid_root")
    return request_xml[start : end + len(end_tag)]


def _normalize_response_raw_xml(
    response_raw: str,
) -> tuple[str | None, str | None, str, str | None]:
    """Read an event answer; anything but ``rRetEnviEventoDe`` is uncertain.

    A SOAP Fault, an HTML page from a proxy or a truncated body arrive after
    the request may have been processed, so they raise
    :class:`SifenUnexpectedResponseError` (outcome unknown) and never a
    validation error.
    """
    try:
        root = ET.fromstring(response_raw.encode("utf-8"))
    except ET.ParseError as exc:
        raise SifenUnexpectedResponseError(
            expected_root=_EVENT_RESPONSE_ROOT,
            actual_root="invalid_xml",
            raw_body=response_raw,
        ) from exc
    root_name = root.tag.rsplit("}", 1)[-1]
    if root_name != _EVENT_RESPONSE_ROOT:
        raise SifenUnexpectedResponseError(
            expected_root=_EVENT_RESPONSE_ROOT,
            actual_root=root_name,
            code=_find_text(root, "dCodRes"),
            response_message=_find_text(root, "dMsgRes"),
            raw_body=response_raw,
        )

    result_code = _find_text(root, "dCodRes")
    result_message = _find_text(root, "dMsgRes")
    protocol = _find_text(root, "dProtAut")
    status_text = (_find_text(root, "dEstRes") or "").strip().lower()

    status = "submitted"
    if "aprob" in status_text:
        status = "approved"
    elif "rechaz" in status_text:
        status = "rejected"

    if result_code in {"0260", "0300", "0600"}:
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
