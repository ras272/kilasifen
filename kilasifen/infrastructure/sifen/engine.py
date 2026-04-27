"""Emission engine adapters built on top of pysifen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

from kilasifen.domain.certificates.models import Certificate
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping
from kilasifen.infrastructure.kude.xml_qr_injector import apply_real_qr_to_signed_xml
from kilasifen.infrastructure.sifen.mapper import PysifenPayloadMapper
from pysifen import PRODUCCION, TEST, sign_xml
from pysifen.sdk.client import SifenClient
from pysifen.sdk.errors import SifenValidationError
from pysifen.transmissao.de import _build_enviar_de_request_xml


@dataclass(slots=True)
class EmissionOutcome:
    """Normalized result from a document emission attempt."""

    generated_xml: str | None
    signed_xml: str
    request_xml: str | None
    response_raw: str | None
    sifen_status: str
    result_code: str | None
    result_message: str | None
    cdc: str | None = None


class DocumentEmissionEngine(Protocol):
    """Contract for document emission engines."""

    def emit_document(
        self,
        *,
        document: Document,
        emitter: Emitter,
        certificate: Certificate,
        certificate_bytes: bytes,
        certificate_password: str,
        stamping: Stamping,
    ) -> EmissionOutcome:
        """Emit one document and return normalized artifacts."""


class PysifenEmissionEngine:
    """Concrete emission engine backed by pysifen transport and signing."""

    def __init__(self, mapper: PysifenPayloadMapper | None = None):
        self.mapper = mapper or PysifenPayloadMapper()
        self.serializer = XmlSerializer(
            config=SerializerConfig(xml_declaration=True, encoding="UTF-8")
        )

    def emit_document(
        self,
        *,
        document: Document,
        emitter: Emitter,
        certificate: Certificate,
        certificate_bytes: bytes,
        certificate_password: str,
        stamping: Stamping,
    ) -> EmissionOutcome:
        del certificate
        emission_input = self.mapper.map_document(
            document,
            emitter=emitter,
            stamping=stamping,
        )
        if emission_input.signed_xml:
            signed_xml = emission_input.signed_xml
            generated_xml = emission_input.generated_xml or emission_input.signed_xml
        else:
            if not emission_input.generated_xml or not emission_input.doc_id:
                raise SifenValidationError(
                    "document payload must include generated_xml and doc_id"
                )
            generated_xml = emission_input.generated_xml
            signed_xml = sign_xml(
                generated_xml,
                certificate_bytes,
                certificate_password,
                emission_input.doc_id,
            )
            signed_xml = apply_real_qr_to_signed_xml(signed_xml, emitter=emitter)

        ambiente = TEST if emitter.tax_environment == "test" else PRODUCCION
        request_xml = _build_enviar_de_request_xml(1, signed_xml).decode("utf-8")

        with SifenClient(
            ambiente=ambiente,
            pkcs12_data=certificate_bytes,
            pkcs12_password=certificate_password,
        ) as client:
            response = client.enviar_de_xml(signed_xml)

        result_code, result_message, status = _normalize_response(response)
        response_raw = self.serializer.render(response)
        return EmissionOutcome(
            generated_xml=generated_xml,
            signed_xml=signed_xml,
            request_xml=request_xml,
            response_raw=response_raw,
            sifen_status=status,
            result_code=result_code,
            result_message=result_message,
            cdc=emission_input.doc_id,
        )


def _normalize_response(response) -> tuple[str | None, str | None, str]:
    result_code = None
    result_message = None
    status = "submitted"

    prot = (
        getattr(response, "rProtDe", None)
        or getattr(response, "gRespProc", None)
        or response
    )
    result_node = _first_result_node(prot)
    for attr in ("dCodRes", "dCodResLot", "dCodResC"):
        value = getattr(result_node, attr, None) or getattr(prot, attr, None)
        if value:
            result_code = str(value)
            break
    for attr in ("dMsgRes", "dMsgResLot", "dMsgResC"):
        value = getattr(result_node, attr, None) or getattr(prot, attr, None)
        if value:
            result_message = str(value)
            break

    status_text = str(getattr(prot, "dEstRes", "") or "").strip().lower()
    if result_code == "0260" or status_text == "aprobado":
        status = "approved"
    elif result_code or status_text == "rechazado":
        status = "rejected"

    return result_code, result_message, status


def _first_result_node(prot):
    result = getattr(prot, "gResProc", None)
    if isinstance(result, list):
        return result[0] if result else prot
    return result or prot
