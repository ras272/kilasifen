"""Payload mappers for the kilasifen.engine emission bridge."""

from dataclasses import dataclass
from xml.etree import ElementTree as ET

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.infrastructure.sifen.typed_xml_builder import build_typed_document_xml


@dataclass(slots=True)
class PysifenEmissionInput:
    """Minimal emission input for the kilasifen.engine bridge."""

    generated_xml: str | None
    signed_xml: str | None
    doc_id: str | None


class PysifenPayloadMapper:
    """Map persisted document payloads into kilasifen.engine-compatible inputs."""

    def map_document(
        self,
        document: Document,
        *,
        emitter: Emitter | None = None,
        stamping: Stamping | None = None,
    ) -> PysifenEmissionInput:
        payload = document.payload_snapshot or {}
        generated_xml = payload.get("generated_xml") or document.generated_xml
        signed_xml = payload.get("signed_xml") or document.signed_xml
        doc_id = payload.get("doc_id") or document.cdc

        if not generated_xml and not signed_xml:
            if emitter is None or stamping is None:
                raise SifenValidationError(
                    "emitter and stamping are required to build typed XML payloads"
                )
            typed_xml = build_typed_document_xml(
                document=document,
                emitter=emitter,
                stamping=stamping,
            )
            if typed_xml is not None:
                generated_xml = typed_xml.generated_xml
                doc_id = typed_xml.doc_id

        if signed_xml and not doc_id:
            doc_id = _extract_doc_id(signed_xml)
        if generated_xml and not doc_id:
            doc_id = _extract_doc_id(generated_xml)

        if not generated_xml and not signed_xml:
            raise SifenValidationError(
                "document payload must include generated_xml or signed_xml"
            )

        return PysifenEmissionInput(
            generated_xml=generated_xml,
            signed_xml=signed_xml,
            doc_id=doc_id,
        )


def _extract_doc_id(xml_text: str) -> str | None:
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        return None

    for element in root.iter():
        if element.tag.endswith("DE"):
            return element.attrib.get("Id")
    return None
