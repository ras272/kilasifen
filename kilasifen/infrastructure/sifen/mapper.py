"""Payload mappers for the pysifen emission bridge."""

from dataclasses import dataclass
from xml.etree import ElementTree as ET

from pysifen.sdk.errors import SifenValidationError

from kilasifen.domain.documents.models import Document


@dataclass(slots=True)
class PysifenEmissionInput:
    """Minimal emission input for the pysifen bridge."""

    generated_xml: str | None
    signed_xml: str | None
    doc_id: str | None


class PysifenPayloadMapper:
    """Map persisted document payloads into pysifen-compatible inputs."""

    def map_document(self, document: Document) -> PysifenEmissionInput:
        payload = document.payload_snapshot or {}
        generated_xml = payload.get("generated_xml")
        signed_xml = payload.get("signed_xml")
        doc_id = payload.get("doc_id")

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
