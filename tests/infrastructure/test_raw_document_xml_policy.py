"""XML policy of the deprecated raw document route and its emission mapping."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from kilasifen.domain.documents.models import Document
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.infrastructure.sifen.mapper import KilaSifenPayloadMapper
from kilasifen.infrastructure.sifen.raw_xml_policy import (
    RawDocumentXmlError,
    validate_raw_document_payload,
    validate_raw_generated_xml,
)
from tests._raw_xml import (
    golden_signed_xml,
    unsigned_rde,
    unsigned_rde_with_extra_child,
)

_SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
_DSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
_SCHEMA_INVALID_RDE = (
    f"<rDE xmlns='{_SIFEN_NS}'><dVerFor>150</dVerFor><DE Id='A1'/></rDE>"
)


@pytest.mark.parametrize("scenario", ["factura_b2b_iva10", "factura_b2g", "nc_total"])
def test_unsigned_valid_rde_is_accepted(scenario: str) -> None:
    generated_xml, doc_id = unsigned_rde(scenario)

    assert validate_raw_generated_xml(generated_xml) == doc_id


def test_platform_signed_shape_is_accepted_as_generated_xml() -> None:
    _generated_xml, doc_id = unsigned_rde()

    assert validate_raw_generated_xml(golden_signed_xml()) == doc_id


@pytest.mark.parametrize(
    ("xml_text", "code"),
    [
        (None, "documents.raw.generated_xml_not_text"),
        ("   ", "documents.raw.generated_xml_not_text"),
        ("<rDE><DE Id='A1'/>", "documents.raw.generated_xml_malformed"),
        ("<rDE><DE Id='A1'/></rDE>", "documents.raw.generated_xml_root_not_rde"),
        (
            f"<rEnviConsRUC xmlns='{_SIFEN_NS}'><dId>1</dId>"
            "<dRUCCons>80024135</dRUCCons></rEnviConsRUC>",
            "documents.raw.generated_xml_root_not_rde",
        ),
        (
            "<!DOCTYPE rDE [<!ENTITY x 'y'>]>"
            f"<rDE xmlns='{_SIFEN_NS}'><dVerFor>&x;</dVerFor></rDE>",
            "documents.raw.generated_xml_doctype_not_allowed",
        ),
        (
            f"<rDE xmlns='{_SIFEN_NS}'><DE Id='A1'/></rDE>",
            "documents.raw.generated_xml_unexpected_element",
        ),
        (_SCHEMA_INVALID_RDE, "documents.raw.generated_xml_invalid_schema"),
    ],
)
def test_unsignable_generated_xml_is_rejected(xml_text: object, code: str) -> None:
    with pytest.raises(RawDocumentXmlError) as raised:
        validate_raw_generated_xml(xml_text)

    assert raised.value.code == code
    assert isinstance(raised.value, SifenValidationError)


def test_schema_errors_do_not_report_the_signature_the_platform_adds() -> None:
    with pytest.raises(RawDocumentXmlError) as raised:
        validate_raw_generated_xml(_SCHEMA_INVALID_RDE)

    assert raised.value.errors
    assert all("xmldsig" not in error for error in raised.value.errors)


@pytest.mark.parametrize(
    "extra_child",
    [
        # A second DE after gCamFuFD: the signer resolves any element by Id.
        f"<DE xmlns='{_SIFEN_NS}' Id='FORGED1'><anything>arbitrary</anything></DE>",
        "<foreign xmlns='urn:example:foreign'>arbitrary unvalidated content</foreign>",
        f"<gCamFuFD xmlns='{_SIFEN_NS}'><dCarQR>x</dCarQR></gCamFuFD>",
        f"<Signature xmlns='{_DSIG_NS}'/>",
    ],
)
def test_elements_outside_the_rde_sequence_are_rejected(extra_child: str) -> None:
    generated_xml = unsigned_rde_with_extra_child(extra_child)

    with pytest.raises(RawDocumentXmlError) as raised:
        validate_raw_document_payload({"generated_xml": generated_xml})

    assert raised.value.code == "documents.raw.generated_xml_unexpected_element"


def test_elements_after_the_missing_signature_are_schema_validated() -> None:
    generated_xml, _doc_id = unsigned_rde()
    invalid_qr_group = generated_xml.replace(
        "<gCamFuFD>", "<gCamFuFD><dNotInSchema>x</dNotInSchema>"
    )
    assert invalid_qr_group != generated_xml

    with pytest.raises(RawDocumentXmlError) as raised:
        validate_raw_generated_xml(invalid_qr_group)

    assert raised.value.code == "documents.raw.generated_xml_invalid_schema"
    assert any("dNotInSchema" in error for error in raised.value.errors)


def test_doc_id_of_another_element_is_rejected() -> None:
    generated_xml, _doc_id = unsigned_rde()

    with pytest.raises(RawDocumentXmlError) as raised:
        validate_raw_document_payload(
            {"generated_xml": generated_xml, "doc_id": "FORGED1"}
        )

    assert raised.value.code == "documents.raw.doc_id_mismatch"


def test_doc_id_inside_typed_contract_must_match_its_generated_xml() -> None:
    generated_xml, _doc_id = unsigned_rde()
    payload = {
        "typed_contract": {
            "contract": "factura_v1",
            "payload": {"generated_xml": generated_xml, "doc_id": "FORGED1"},
        }
    }

    with pytest.raises(RawDocumentXmlError) as raised:
        validate_raw_document_payload(payload)

    assert raised.value.code == "documents.raw.doc_id_mismatch"


@pytest.mark.parametrize("requested", ["matching", None, ""])
def test_doc_id_matching_the_de_or_absent_is_accepted(requested) -> None:
    generated_xml, doc_id = unsigned_rde()
    doc_id_value = doc_id if requested == "matching" else requested

    validate_raw_document_payload(
        {"generated_xml": generated_xml, "doc_id": doc_id_value}
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"signed_xml": "<rDE/>"},
        {
            "typed_contract": {
                "contract": "factura_v1",
                "payload": {"signed_xml": "<rDE/>"},
            }
        },
    ],
)
def test_caller_signed_xml_is_never_accepted(payload: dict) -> None:
    with pytest.raises(RawDocumentXmlError) as raised:
        validate_raw_document_payload(payload)

    assert raised.value.code == "documents.raw.signed_xml_not_allowed"


def test_generated_xml_inside_typed_contract_is_validated() -> None:
    payload = {
        "typed_contract": {
            "contract": "factura_v1",
            "payload": {"generated_xml": "<rDE><DE Id='A1'/></rDE>"},
        }
    }

    with pytest.raises(RawDocumentXmlError) as raised:
        validate_raw_document_payload(payload)

    assert raised.value.code == "documents.raw.generated_xml_root_not_rde"


@pytest.mark.parametrize("payload", [None, {}, {"total": "1000"}])
def test_payload_without_xml_passes_the_raw_policy(payload: dict | None) -> None:
    validate_raw_document_payload(payload)


def test_mapper_ignores_caller_signed_xml_and_signs_validated_generated_xml() -> None:
    generated_xml, doc_id = unsigned_rde()
    document = _document(
        payload_snapshot={
            "generated_xml": generated_xml,
            "signed_xml": "<rDE>externally signed</rDE>",
            "doc_id": doc_id,
        }
    )

    emission_input = KilaSifenPayloadMapper().map_document(document)

    assert emission_input.signed_xml is None
    assert emission_input.generated_xml == generated_xml
    assert emission_input.doc_id == doc_id


def test_mapper_refuses_a_legacy_payload_with_only_caller_signed_xml() -> None:
    document = _document(payload_snapshot={"signed_xml": golden_signed_xml()})

    with pytest.raises(SifenValidationError):
        KilaSifenPayloadMapper().map_document(document)


def test_mapper_signs_only_the_validated_de_without_a_caller_doc_id() -> None:
    generated_xml, doc_id = unsigned_rde()
    document = _document(payload_snapshot={"generated_xml": generated_xml})

    emission_input = KilaSifenPayloadMapper().map_document(document)

    assert emission_input.doc_id == doc_id


def test_mapper_refuses_a_doc_id_that_is_not_the_validated_de() -> None:
    generated_xml, _doc_id = unsigned_rde()
    document = _document(
        payload_snapshot={"generated_xml": generated_xml, "doc_id": "FORGED1"}
    )

    with pytest.raises(RawDocumentXmlError) as raised:
        KilaSifenPayloadMapper().map_document(document)

    assert raised.value.code == "documents.raw.doc_id_mismatch"


def test_mapper_refuses_raw_xml_with_a_trailing_element() -> None:
    generated_xml = unsigned_rde_with_extra_child(
        f"<DE xmlns='{_SIFEN_NS}' Id='FORGED1'><anything/></DE>"
    )
    document = _document(
        payload_snapshot={"generated_xml": generated_xml, "doc_id": "FORGED1"}
    )

    with pytest.raises(RawDocumentXmlError) as raised:
        KilaSifenPayloadMapper().map_document(document)

    assert raised.value.code == "documents.raw.generated_xml_unexpected_element"


def test_mapper_validates_raw_generated_xml_before_signing() -> None:
    document = _document(
        payload_snapshot={"generated_xml": "<rDE><DE Id='A1'/></rDE>", "doc_id": "A1"}
    )

    with pytest.raises(RawDocumentXmlError):
        KilaSifenPayloadMapper().map_document(document)


def test_mapper_reuses_xml_the_platform_already_signed() -> None:
    signed_xml = golden_signed_xml()
    document = replace(
        _document(
            payload_snapshot={
                "generated_xml": "<rDE><DE Id='A1'/></rDE>",
                "doc_id": "A1",
            }
        ),
        signed_xml=signed_xml,
    )

    emission_input = KilaSifenPayloadMapper().map_document(document)

    assert emission_input.signed_xml == signed_xml


def _document(*, payload_snapshot: dict) -> Document:
    now = datetime.now(timezone.utc)
    return Document(
        id="doc-raw",
        emitter_id="emitter-1",
        external_id="erp-raw",
        idempotency_key="idem-raw",
        document_type="factura",
        payload_snapshot=payload_snapshot,
        generated_xml=None,
        signed_xml=None,
        sifen_request_xml=None,
        sifen_response_raw=None,
        last_query_request_xml=None,
        last_query_response_raw=None,
        last_query_at=None,
        cdc=None,
        internal_status="queued",
        sifen_status=None,
        sifen_result_code=None,
        sifen_result_message=None,
        created_at=now,
        updated_at=now,
    )
