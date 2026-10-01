"""Payload mappers for the kilasifen.engine emission bridge."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from lxml import etree

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.engine.sdk.validation import validate_xml
from kilasifen.infrastructure.sifen.typed_xml_builder import build_typed_document_xml

_SIFEN_NAMESPACE = "http://ekuatia.set.gov.py/sifen/xsd"
_RDE_TAG = f"{{{_SIFEN_NAMESPACE}}}rDE"

# Schema errors that an unsigned rDE always or legitimately produces. They are
# the same two the typed XML builder tolerates before signing: the Signature
# is added by the platform when it signs, and DE_v150.xsd declares
# "dEntCont " with a trailing space, which rejects every valid dEntCont.
_TOLERATED_UNSIGNED_SCHEMA_ERRORS = (
    "{http://www.w3.org/2000/09/xmldsig#}Signature",
    f"Expected is ( {{{_SIFEN_NAMESPACE}}}dEntCont  )",
)
_MAX_REPORTED_SCHEMA_ERRORS = 5
_MAX_SCHEMA_ERROR_LENGTH = 300


class RawDocumentXmlError(SifenValidationError):
    """Caller-supplied XML of the deprecated raw route cannot be signed."""

    def __init__(self, code: str, errors: Sequence[str] = ()) -> None:
        super().__init__(f"{code}:{errors[0]}" if errors else code)
        self.code = code
        self.errors = tuple(errors)


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
        if raw_generated_xml and not signed_xml:
            validate_raw_generated_xml(raw_generated_xml)
        generated_xml = raw_generated_xml or document.generated_xml
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

        return KilaSifenEmissionInput(
            generated_xml=generated_xml,
            signed_xml=signed_xml,
            doc_id=doc_id,
        )


def validate_raw_document_payload(payload: dict | None) -> None:
    """Enforce the XML policy of the deprecated raw document route.

    The raw route may carry an unsigned ``generated_xml`` that the platform
    signs with the emitter certificate, so it must be an XSD-valid ``rDE``.
    A caller-supplied ``signed_xml`` is never accepted: it would travel
    through the emitter's mTLS channel without the platform having signed it.
    Both keys are checked at the top level and inside ``typed_contract``,
    whose values the document service copies to the top level.
    """

    for section in _xml_sections(payload):
        if section.get("signed_xml") is not None:
            raise RawDocumentXmlError("documents.raw.signed_xml_not_allowed")
        generated_xml = section.get("generated_xml")
        if generated_xml is not None:
            validate_raw_generated_xml(generated_xml)


def validate_raw_generated_xml(xml_text: object) -> None:
    """Accept only an unsigned SIFEN ``rDE`` that passes the official XSD."""

    if not isinstance(xml_text, str) or not xml_text.strip():
        raise RawDocumentXmlError("documents.raw.generated_xml_not_text")

    root = _parse_untrusted_xml(xml_text)
    if root.tag != _RDE_TAG:
        raise RawDocumentXmlError("documents.raw.generated_xml_root_not_rde")

    schema_errors = [
        error[:_MAX_SCHEMA_ERROR_LENGTH]
        for error in validate_xml(xml_text)
        if not any(marker in error for marker in _TOLERATED_UNSIGNED_SCHEMA_ERRORS)
    ]
    if schema_errors:
        raise RawDocumentXmlError(
            "documents.raw.generated_xml_invalid_schema",
            schema_errors[:_MAX_REPORTED_SCHEMA_ERRORS],
        )


def _xml_sections(payload: dict | None) -> Iterator[dict]:
    if not isinstance(payload, dict):
        return
    yield payload
    typed_contract = payload.get("typed_contract")
    if isinstance(typed_contract, dict) and isinstance(
        typed_contract.get("payload"), dict
    ):
        yield typed_contract["payload"]


def _parse_untrusted_xml(xml_text: str) -> etree._Element:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
    )
    try:
        root = etree.fromstring(xml_text.encode("utf-8"), parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise RawDocumentXmlError(
            "documents.raw.generated_xml_malformed",
            [str(exc)[:_MAX_SCHEMA_ERROR_LENGTH]],
        ) from exc
    if root.getroottree().docinfo.doctype:
        raise RawDocumentXmlError("documents.raw.generated_xml_doctype_not_allowed")
    return root


def _extract_doc_id(xml_text: str) -> str | None:
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        return None

    for element in root.iter():
        if element.tag.endswith("DE"):
            return element.attrib.get("Id")
    return None
