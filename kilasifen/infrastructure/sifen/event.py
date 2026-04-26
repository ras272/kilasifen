"""Fiscal event submission adapters backed by pysifen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

from pysifen import PRODUCCION, TEST
from pysifen.de.bindings.v150.evento_v150 import TgGroupGesEve
from pysifen.de.bindings.v150.ws_si_recep_evento_v150 import REnviEventoDe
from pysifen.sdk.client import SifenClient
from pysifen.sdk.errors import SifenRejectionError, SifenValidationError
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
        group = TgGroupGesEve.from_xml(event_xml)
        request = REnviEventoDe(
            dId=_generate_id(),
            dEvReg=REnviEventoDe.DEvReg(gGroupGesEve=group),
        )
        request_xml = self.serializer.render(request)

        ambiente = TEST if emitter.tax_environment == "test" else PRODUCCION
        with SifenClient(
            ambiente=ambiente,
            pkcs12_data=certificate_bytes,
            pkcs12_password=certificate_password,
        ) as client:
            response = client.enviar_evento(group)

        response_raw = self.serializer.render(response)
        result_code, result_message, status, protocol = _normalize_response(response)
        if status == "rejected":
            raise SifenRejectionError(
                result_code or "unknown",
                result_message or "event rejected by sifen",
            )

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
