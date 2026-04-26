import os
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from pysifen.assinatura import sign_xml
from pysifen.sdk.validation import validate_xml

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping
from kilasifen.infrastructure.kude.xml_qr_injector import apply_real_qr_to_signed_xml
from kilasifen.infrastructure.sifen.typed_xml_builder import build_typed_document_xml
from kilasifen.testing.typed_contract_scenarios import (
    TypedContractScenario,
    get_typed_contract_scenarios,
)

_GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"
_CERT_PATH = Path(__file__).resolve().parents[1] / "test_cert.pfx"
_CERT_PASSWORD = "test1234"
_UPDATE_GOLDENS = os.getenv("KILA_SIFEN_UPDATE_GOLDENS") == "1"


@pytest.fixture(scope="module")
def cert_data() -> bytes:
    if not _CERT_PATH.exists():
        pytest.skip("test_cert.pfx not found")
    return _CERT_PATH.read_bytes()


@pytest.mark.parametrize(
    "scenario",
    get_typed_contract_scenarios(),
    ids=lambda s: s.name,
)
def test_signed_typed_xml_matches_golden(
    scenario: TypedContractScenario,
    cert_data: bytes,
) -> None:
    emitter = _build_emitter()
    typed = build_typed_document_xml(
        document=_build_document(scenario),
        emitter=emitter,
        stamping=_build_stamping(),
    )
    assert typed is not None

    signed_xml = sign_xml(
        typed.generated_xml,
        cert_data,
        _CERT_PASSWORD,
        typed.doc_id,
    )
    signed_xml = apply_real_qr_to_signed_xml(signed_xml, emitter=emitter)
    assert "ds:" not in signed_xml
    assert "<!--" not in signed_xml
    schema_errors = [
        error
        for error in validate_xml(signed_xml)
        if "Expected is ( {http://ekuatia.set.gov.py/sifen/xsd}dEntCont  )" not in error
    ]
    assert schema_errors == []

    golden_path = _GOLDEN_DIR / f"{scenario.name}.xml"
    if _UPDATE_GOLDENS:
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        golden_path.write_bytes(signed_xml.encode("utf-8"))

    assert golden_path.exists(), (
        f"Golden file missing: {golden_path}. "
        "Run with KILA_SIFEN_UPDATE_GOLDENS=1 to create/update snapshots."
    )
    assert signed_xml.encode("utf-8") == golden_path.read_bytes()


def test_golden_coverage_matches_expected_names() -> None:
    expected = sorted([f"{scenario.name}.xml" for scenario in get_typed_contract_scenarios()])
    existing = sorted([path.name for path in _GOLDEN_DIR.glob("*.xml")])
    assert existing == expected


def _build_document(scenario: TypedContractScenario) -> Document:
    timestamp = _now()
    payload_snapshot = {
        "typed_contract": {
            "contract": scenario.contract,
            "payload": scenario.payload,
        }
    }
    return Document(
        id=f"doc-{scenario.name}",
        emitter_id="emitter-1",
        external_id=f"erp-{scenario.name}",
        idempotency_key=f"idem-{scenario.name}",
        document_type=scenario.document_type,
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
        created_at=timestamp,
        updated_at=timestamp,
    )


def _build_emitter() -> Emitter:
    timestamp = _now()
    return Emitter(
        id="emitter-1",
        external_id="erp-ares",
        ruc="80024135",
        dv="5",
        legal_name="ARES PARAGUAY SRL",
        tax_environment="test",
        status="active",
        csc="ABCD0000000000000000000000000000",
        csc_id="0001",
        created_at=timestamp,
        updated_at=timestamp,
    )


def _build_stamping() -> Stamping:
    timestamp = _now()
    return Stamping(
        id="stamp-1",
        emitter_id="emitter-1",
        number="80024135",
        start_date=date(2024, 3, 11),
        end_date=None,
        is_active=True,
        status="active",
        created_at=timestamp,
        updated_at=timestamp,
    )


def _now() -> datetime:
    return datetime.now(UTC)
