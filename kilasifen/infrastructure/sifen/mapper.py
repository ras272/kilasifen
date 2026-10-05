"""Payload mappers for the kilasifen.engine emission bridge."""

from dataclasses import dataclass
from datetime import date
from xml.etree import ElementTree as ET

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.infrastructure.sifen.de_facts import read_de_facts
from kilasifen.infrastructure.sifen.raw_xml_policy import signable_doc_id
from kilasifen.infrastructure.sifen.typed_xml_builder import (
    _resolve_emission_datetime,
    build_typed_document_xml,
)


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
    """Map persisted document payloads into kilasifen.engine-compatible inputs."""

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


def resolve_emission_date(document: Document) -> date | None:
    """Date of ``dFeEmiDE`` (D002) the document carries or will carry.

    The timbrado is chosen with this date, not the server date: it must be
    active on D002 and D002 cannot precede its start (1103 as amended by NT
    01, 1104; MT v150 §12.4 p. 160; DECISIONES F23). An XML already built
    (stored, or supplied by the caller) decides; otherwise the typed payload,
    read exactly as the builder reads it. ``None`` when neither says.

    Raises:
        SifenValidationError: if the typed payload carries an invalid date.
    """

    payload = document.payload_snapshot or {}
    for xml_text in (
        document.signed_xml,
        document.generated_xml,
        payload.get("generated_xml"),
    ):
        issued_at = read_de_facts(xml_text).issued_at
        if issued_at is not None:
            return issued_at.date()

    typed_contract = payload.get("typed_contract")
    if not isinstance(typed_contract, dict):
        return None
    typed_payload = typed_contract.get("payload")
    if not isinstance(typed_payload, dict):
        return None
    return date.fromisoformat(_resolve_emission_datetime(typed_payload)[:10])


def _extract_doc_id(xml_text: str) -> str | None:
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        return None

    for element in root.iter():
        if element.tag.endswith("DE"):
            return element.attrib.get("Id")
    return None
