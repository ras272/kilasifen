"""XML policy of the deprecated raw document route.

The raw route lets ``platform:admin`` hand the platform an unsigned ``rDE``
that the worker signs with the emitter certificate. To keep that route from
working as a signing oracle, the XML must be exactly one SIFEN ``rDE`` that
passes the official XSD, and the only node the platform signs is its ``DE``.
"""

from collections.abc import Iterator, Sequence
from copy import deepcopy

from lxml import etree

from kilasifen.domain.common.errors import UnprocessableEntityError
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.engine.sdk.validation import validate_xml

_SIFEN_NAMESPACE = "http://ekuatia.set.gov.py/sifen/xsd"
_XMLDSIG_NAMESPACE = "http://www.w3.org/2000/09/xmldsig#"
_RDE_TAG = f"{{{_SIFEN_NAMESPACE}}}rDE"
_DVERFOR_TAG = f"{{{_SIFEN_NAMESPACE}}}dVerFor"
_DE_TAG = f"{{{_SIFEN_NAMESPACE}}}DE"
_GCAMFUFD_TAG = f"{{{_SIFEN_NAMESPACE}}}gCamFuFD"
_SIGNATURE_TAG = f"{{{_XMLDSIG_NAMESPACE}}}Signature"

# Children the official rDE sequence allows, in order, after dVerFor and DE.
# The Signature may be absent because the platform adds it when it signs;
# whether gCamFuFD is required is left to the XSD.
_ALLOWED_RDE_TAILS = (
    (),
    (_SIGNATURE_TAG,),
    (_GCAMFUFD_TAG,),
    (_SIGNATURE_TAG, _GCAMFUFD_TAG),
)
_RDE_LAYOUT_ERROR = (
    "rDE must contain, in this order, dVerFor, one DE, an optional "
    "ds:Signature and gCamFuFD, and no other element."
)

# Schema-valid stand-in for the Signature the platform adds when it signs.
# It is only used to validate a copy of the caller's XML: with the Signature
# missing, libxml2 stops validating every element that follows DE.
_PLACEHOLDER_SIGNATURE = (
    f'<Signature xmlns="{_XMLDSIG_NAMESPACE}"><SignedInfo>'
    '<CanonicalizationMethod Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#"/>'
    '<SignatureMethod Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"/>'
    '<Reference URI=""><DigestMethod '
    'Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>'
    "<DigestValue></DigestValue></Reference>"
    "</SignedInfo><SignatureValue></SignatureValue></Signature>"
)

# DE_v150.xsd declares "dEntCont " with a trailing space, which rejects every
# valid dEntCont. The typed XML builder tolerates the same error.
_TOLERATED_SCHEMA_ERROR = (
    f"Element '{{{_SIFEN_NAMESPACE}}}dEntCont': This element is not expected. "
    f"Expected is ( {{{_SIFEN_NAMESPACE}}}dEntCont  )."
)
_MAX_REPORTED_SCHEMA_ERRORS = 5
_MAX_SCHEMA_ERROR_LENGTH = 300


class RawDocumentXmlError(SifenValidationError):
    """Caller-supplied XML of the deprecated raw route cannot be signed."""

    def __init__(self, code: str, errors: Sequence[str] = ()) -> None:
        super().__init__(f"{code}:{errors[0]}" if errors else code)
        self.code = code
        self.errors = tuple(errors)


def validate_raw_document_payload(payload: dict | None) -> None:
    """Enforce the XML policy of the deprecated raw document route.

    A caller-supplied ``signed_xml`` is never accepted: it would travel
    through the emitter's mTLS channel without the platform having signed
    it. A ``generated_xml`` must pass :func:`validate_raw_generated_xml`, and
    a ``doc_id`` sent with it must be the ``Id`` of its ``DE``. Both keys are
    checked at the top level and inside ``typed_contract``, whose values the
    document service copies to the top level.
    """

    for section in _xml_sections(payload):
        if section.get("signed_xml") is not None:
            raise RawDocumentXmlError("documents.raw.signed_xml_not_allowed")
        generated_xml = section.get("generated_xml")
        if generated_xml is not None:
            signable_doc_id(
                generated_xml=generated_xml,
                requested_doc_id=section.get("doc_id"),
            )


def require_signable_raw_payload(payload: dict | None) -> None:
    """Apply :func:`validate_raw_document_payload` for the document service.

    Raises ``UnprocessableEntityError`` with the policy code and, for schema
    errors, the validator messages in ``details["errors"]``.
    """

    try:
        validate_raw_document_payload(payload)
    except RawDocumentXmlError as exc:
        raise UnprocessableEntityError(
            exc.code,
            details={"errors": list(exc.errors)} if exc.errors else None,
        ) from exc


def signable_doc_id(*, generated_xml: object, requested_doc_id: object) -> str:
    """Validate raw ``generated_xml`` and return the ``Id`` the platform signs.

    ``requested_doc_id`` is the caller's ``doc_id``. When present (not
    ``None`` or empty) it must be the ``Id`` of the validated ``DE``; the
    signature never references any other element.
    """

    doc_id = validate_raw_generated_xml(generated_xml)
    if requested_doc_id not in (None, "") and requested_doc_id != doc_id:
        raise RawDocumentXmlError("documents.raw.doc_id_mismatch")
    return doc_id


def validate_raw_generated_xml(xml_text: object) -> str:
    """Accept only one SIFEN ``rDE`` that passes the official XSD.

    Returns the ``Id`` of its ``DE``, the only node the platform signs.
    """

    if not isinstance(xml_text, str) or not xml_text.strip():
        raise RawDocumentXmlError("documents.raw.generated_xml_not_text")

    root = _parse_untrusted_xml(xml_text)
    if root.tag != _RDE_TAG:
        raise RawDocumentXmlError("documents.raw.generated_xml_root_not_rde")
    _require_rde_layout(root)

    schema_errors = [
        error[:_MAX_SCHEMA_ERROR_LENGTH]
        for error in validate_xml(_with_placeholder_signature(root))
        if _TOLERATED_SCHEMA_ERROR not in error
    ]
    if schema_errors:
        raise RawDocumentXmlError(
            "documents.raw.generated_xml_invalid_schema",
            schema_errors[:_MAX_REPORTED_SCHEMA_ERRORS],
        )
    return root.find(_DE_TAG).get("Id")


def _require_rde_layout(root: etree._Element) -> None:
    tags = tuple(child.tag for child in root if isinstance(child.tag, str))
    if tags[:2] != (_DVERFOR_TAG, _DE_TAG) or tags[2:] not in _ALLOWED_RDE_TAILS:
        raise RawDocumentXmlError(
            "documents.raw.generated_xml_unexpected_element",
            [_RDE_LAYOUT_ERROR],
        )


def _with_placeholder_signature(root: etree._Element) -> str:
    """Serialize a copy of ``root`` whose Signature is the placeholder.

    The signer drops any existing Signature and inserts its own right after
    ``DE``, so the copy mirrors the shape of the XML that will be signed.
    """

    candidate = deepcopy(root)
    for signature in candidate.findall(_SIGNATURE_TAG):
        candidate.remove(signature)
    candidate.find(_DE_TAG).addnext(etree.fromstring(_PLACEHOLDER_SIGNATURE))
    return etree.tostring(candidate, encoding="unicode")


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
