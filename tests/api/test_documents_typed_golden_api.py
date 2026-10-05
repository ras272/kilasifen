import xml.etree.ElementTree as ET
from collections.abc import Iterator
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.api.deps import get_fiscal_clock
from kilasifen.config import get_settings
from kilasifen.domain.common.paraguay_time import PARAGUAY_TZ
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.fiscal_profile import fiscal_profile_from_dict
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.stampings.models import Stamping
from kilasifen.engine.firma import sign_xml
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.session import build_engine
from kilasifen.infrastructure.kude.xml_qr_injector import apply_real_qr_to_signed_xml
from kilasifen.infrastructure.sifen.mapper import KilaSifenPayloadMapper
from kilasifen.testing.database import managed_test_database_url
from kilasifen.testing.fiscal_profiles import fictional_fiscal_profile_payload
from kilasifen.testing.typed_contract_scenarios import (
    GOLDEN_SIGNED_AT,
    TypedContractScenario,
    get_typed_contract_scenarios,
)

API_KEY = "secret-key"
_GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"
_CERT_PATH = Path(__file__).resolve().parents[1] / "test_cert.pfx"
_CERT_PASSWORD = "test1234"
_TEST_CSC = "ABCD0000000000000000000000000000"
_TEST_CSC_ID = "0001"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def cert_data() -> bytes:
    if not _CERT_PATH.exists():
        pytest.skip("test_cert.pfx not found")
    return _CERT_PATH.read_bytes()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    with managed_test_database_url(
        tmp_path=tmp_path, name="typed_documents_golden"
    ) as database_url:
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{API_KEY}"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

        engine = build_engine(database_url)
        Base.metadata.create_all(engine)

        app = create_app()
        # The scenarios are issued on 2026-04-25T10:00:00 and signed at
        # GOLDEN_SIGNED_AT; creation happens at that same moment.
        app.dependency_overrides[get_fiscal_clock] = lambda: lambda: (
            GOLDEN_SIGNED_AT.replace(tzinfo=PARAGUAY_TZ)
        )
        with TestClient(app) as test_client:
            yield test_client


@pytest.mark.parametrize(
    "scenario",
    get_typed_contract_scenarios(),
    ids=lambda s: s.name,
)
def test_typed_documents_api_scenarios_match_golden_and_isolation(
    scenario: TypedContractScenario,
    client: TestClient,
    cert_data: bytes,
) -> None:
    emitter_a = _create_emitter(
        client, external_id=f"erp-{scenario.name}-a", ruc="80024135", dv="5"
    )
    emitter_b = _create_emitter(
        client, external_id=f"erp-{scenario.name}-b", ruc="80111111", dv="0"
    )

    first = _create_typed_document(
        client=client, emitter_id=emitter_a["id"], scenario=scenario, suffix="1"
    )
    assert first.status_code == 201
    first_document = first.json()["data"]["document"]
    assert first_document["document_type"] == scenario.document_type
    assert first_document["emitter_id"] == emitter_a["id"]
    assert first_document["document_number"] == 1
    assert (
        first_document["payload_snapshot"]["typed_contract"]["contract"]
        == scenario.contract
    )

    signed_xml = _build_signed_xml_from_api_document(
        api_document=first_document,
        emitter=emitter_a,
        cert_data=cert_data,
    )
    golden_path = _GOLDEN_DIR / f"{scenario.name}.xml"
    assert golden_path.exists(), (
        f"Golden file missing for scenario {scenario.name}: {golden_path}"
    )
    assert _without_signature(signed_xml.encode("utf-8")) == _without_signature(
        golden_path.read_bytes()
    )

    second = _create_typed_document(
        client=client, emitter_id=emitter_a["id"], scenario=scenario, suffix="2"
    )
    assert second.status_code == 201
    second_document = second.json()["data"]["document"]
    assert second_document["document_number"] == 2

    isolated = client.get(
        f"/v1/emitters/{emitter_b['id']}/documents/{first_document['id']}/xml",
        headers={"X-API-Key": API_KEY},
    )
    assert isolated.status_code == 404


def _create_typed_document(
    *,
    client: TestClient,
    emitter_id: str,
    scenario: TypedContractScenario,
    suffix: str,
):
    payload = deepcopy(scenario.payload)
    if scenario.document_type == "factura":
        endpoint = f"/v1/emitters/{emitter_id}/documents/facturas"
        body = {
            "external_id": f"{scenario.name}-{suffix}",
            "idempotency_key": f"{scenario.name}-idem-{suffix}",
            "factura": payload,
        }
    elif scenario.document_type == "nota_credito":
        endpoint = f"/v1/emitters/{emitter_id}/documents/notas-credito"
        body = {
            "external_id": f"{scenario.name}-{suffix}",
            "idempotency_key": f"{scenario.name}-idem-{suffix}",
            "nota_credito": payload,
        }
    else:
        endpoint = f"/v1/emitters/{emitter_id}/documents/notas-debito"
        body = {
            "external_id": f"{scenario.name}-{suffix}",
            "idempotency_key": f"{scenario.name}-idem-{suffix}",
            "nota_debito": payload,
        }
    return client.post(endpoint, headers={"X-API-Key": API_KEY}, json=body)


def _without_signature(xml: bytes) -> bytes:
    """Compare the fiscal payload while allowing an ephemeral signing key."""

    root = ET.fromstring(xml)
    signature = root.find("{http://www.w3.org/2000/09/xmldsig#}Signature")
    if signature is not None:
        root.remove(signature)
    return ET.tostring(root, encoding="utf-8")


def _create_emitter(client: TestClient, *, external_id: str, ruc: str, dv: str) -> dict:
    response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": external_id,
            "ruc": ruc,
            "dv": dv,
            "legal_name": "ARES PARAGUAY SRL",
            "tax_environment": "test",
            "csc": _TEST_CSC,
            "csc_id": _TEST_CSC_ID,
            "fiscal_profile": fictional_fiscal_profile_payload(),
        },
    )
    assert response.status_code == 201
    return response.json()["data"]["emitter"]


def _build_signed_xml_from_api_document(
    *, api_document: dict, emitter: dict, cert_data: bytes
) -> str:
    document = Document(
        id=api_document["id"],
        emitter_id=api_document["emitter_id"],
        external_id=api_document.get("external_id"),
        idempotency_key=api_document.get("idempotency_key"),
        document_type=api_document["document_type"],
        payload_snapshot=api_document["payload_snapshot"],
        generated_xml=api_document.get("generated_xml"),
        signed_xml=api_document.get("signed_xml"),
        sifen_request_xml=api_document.get("sifen_request_xml"),
        sifen_response_raw=api_document.get("sifen_response_raw"),
        last_query_request_xml=api_document.get("last_query_request_xml"),
        last_query_response_raw=api_document.get("last_query_response_raw"),
        last_query_at=None,
        cdc=api_document.get("cdc"),
        internal_status=api_document["internal_status"],
        sifen_status=api_document.get("sifen_status"),
        sifen_result_code=api_document.get("sifen_result_code"),
        sifen_result_message=api_document.get("sifen_result_message"),
        created_at=_parse_datetime(api_document["created_at"]),
        updated_at=_parse_datetime(api_document["updated_at"]),
        establishment=api_document.get("establishment"),
        point=api_document.get("point"),
        document_number=api_document.get("document_number"),
    )
    emitter_obj = Emitter(
        id=emitter["id"],
        external_id=emitter["external_id"],
        ruc=emitter["ruc"],
        dv=emitter["dv"],
        legal_name=emitter["legal_name"],
        tax_environment=emitter["tax_environment"],
        status=emitter["status"],
        # Secret write-only fields are intentionally absent from API responses.
        csc=_TEST_CSC,
        csc_id=_TEST_CSC_ID,
        created_at=_parse_datetime(emitter["created_at"]),
        updated_at=_parse_datetime(emitter["updated_at"]),
        fiscal_profile=fiscal_profile_from_dict(emitter["fiscal_profile"]),
    )
    mapper = KilaSifenPayloadMapper()
    emission_input = mapper.map_document(
        document,
        emitter=emitter_obj,
        stamping=_build_stamping(emitter["id"]),
        signed_at=GOLDEN_SIGNED_AT,
    )
    assert emission_input.generated_xml is not None
    assert emission_input.doc_id is not None
    signed_xml = sign_xml(
        emission_input.generated_xml,
        cert_data,
        _CERT_PASSWORD,
        emission_input.doc_id,
    )
    return apply_real_qr_to_signed_xml(signed_xml, emitter=emitter_obj)


def _build_stamping(emitter_id: str) -> Stamping:
    timestamp = _now()
    return Stamping(
        id="stamping-test",
        emitter_id=emitter_id,
        number="80024135",
        start_date=date(2024, 3, 11),
        end_date=None,
        is_active=True,
        status="active",
        created_at=timestamp,
        updated_at=timestamp,
    )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _now() -> datetime:
    return datetime.now(timezone.utc)
