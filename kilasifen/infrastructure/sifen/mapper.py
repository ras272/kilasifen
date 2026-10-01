"""Payload mappers for the kilasifen.engine emission bridge."""

from dataclasses import dataclass
from xml.etree import ElementTree as ET

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.infrastructure.sifen.raw_xml_policy import signable_doc_id
from kilasifen.infrastructure.sifen.typed_xml_builder import build_typed_document_xml


@dataclass(slots=True)
class KilaSifenEmissionInput:
    """Minimal emission input for the kilasifen.engine bridge.

    ``signed_xml`` is only ever XML the platform signed itself in an earlier
    attempt (``Document.signed_xml``), never XML supplied by a caller.
    """

    generated_xml: str | None
    signed_xml: str | None
    doc_id: str | None


class KilaSifenPayloadMapper:
    """Map persisted document payloads into kilasifen.engine-compatible inputs.

    ``test_emitter_name_literal`` is the ``dNomEmi`` written for emitters of
    the SIFEN test environment (``KILA_SIFEN_TEST_EMITTER_NAME_LITERAL``);
    ``None`` keeps the legal name.
    """

    def __init__(self, test_emitter_name_literal: str | None = None) -> None:
        self.test_emitter_name_literal = test_emitter_name_literal

    def map_document(
        self,
        document: Document,
        *,
        emitter: Emitter | None = None,
        stamping: Stamping | None = None,
    ) -> KilaSifenEmissionInput:
        payload = document.payload_snapshot or {}
        signed_xml = document.signed_xml
        raw_generated_xml = payload.get("generated_xml")
        generated_xml = raw_generated_xml or document.generated_xml
        doc_id = payload.get("doc_id") or document.cdc
        if raw_generated_xml and not signed_xml:
            # Caller-supplied XML: sign only the DE that passed the policy.
            doc_id = signable_doc_id(
                generated_xml=raw_generated_xml,
                requested_doc_id=payload.get("doc_id"),
            )

        if not generated_xml and not signed_xml:
            if emitter is None or stamping is None:
                raise SifenValidationError(
                    "emitter and stamping are required to build typed XML payloads"
                )
            typed_xml = build_typed_document_xml(
                document=document,
                emitter=emitter,
                stamping=stamping,
                test_emitter_name_literal=self.test_emitter_name_literal,
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

        return KilaSifenEmissionInput(
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
