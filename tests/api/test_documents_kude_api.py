"""API tests for the KuDE PDF and JSON data endpoints."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.config import get_settings
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.session import build_engine
from kilasifen.infrastructure.kude.qr_generator import build_sifen_qr_url
from kilasifen.testing.database import managed_test_database_url

API_KEY = "secret-key"
_GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"
_CSC = "ABCD0000000000000000000000000000"
_CSC_ID = "0001"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    with managed_test_database_url(
        tmp_path=tmp_path, name="documents_kude"
    ) as database_url:
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{API_KEY}"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

        engine = build_engine(database_url)
        Base.metadata.create_all(engine)

        with TestClient(create_app()) as test_client:
            yield test_client


def _create_emitter(
    client: TestClient,
    *,
    external_id: str,
    ruc: str,
    dv: str,
    csc: str | None = _CSC,
    csc_id: str | None = _CSC_ID,
) -> dict:
    response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": external_id,
            "ruc": ruc,
            "dv": dv,
            "legal_name": "ARES PARAGUAY SRL",
            "tax_environment": "test",
            "csc": csc,
            "csc_id": csc_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["emitter"]


def _create_document_with_signed_xml(
    client: TestClient, *, emitter_id: str, scenario_name: str, document_type: str
) -> dict:
    signed_xml = (_GOLDEN_DIR / f"{scenario_name}.xml").read_text(encoding="utf-8")
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": f"erp-{scenario_name}",
            "idempotency_key": f"idem-{scenario_name}",
            "document_type": document_type,
            "payload": {"signed_xml": signed_xml},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["document"]


def test_get_kude_returns_pdf(client: TestClient):
    emitter = _create_emitter(client, external_id="erp-a", ruc="80024135", dv="5")
    document = _create_document_with_signed_xml(
        client,
        emitter_id=emitter["id"],
        scenario_name="factura_b2b_iva10",
        document_type="factura",
    )
    response = client.get(
        f"/v1/emitters/{emitter['id']}/documents/{document['id']}/kude",
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content[:5] == b"%PDF-"


def test_get_kude_isolates_documents_across_emitters(client: TestClient):
    emitter_a = _create_emitter(client, external_id="erp-a", ruc="80024135", dv="5")
    emitter_b = _create_emitter(client, external_id="erp-b", ruc="80111111", dv="9")
    document = _create_document_with_signed_xml(
        client,
        emitter_id=emitter_a["id"],
        scenario_name="factura_b2b_iva10",
        document_type="factura",
    )
    response = client.get(
        f"/v1/emitters/{emitter_b['id']}/documents/{document['id']}/kude",
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 404


def test_get_kude_requires_emitter_csc(client: TestClient):
    emitter = _create_emitter(
        client,
        external_id="erp-no-csc",
        ruc="80024135",
        dv="5",
        csc=None,
        csc_id=None,
    )
    document = _create_document_with_signed_xml(
        client,
        emitter_id=emitter["id"],
        scenario_name="factura_b2b_iva10",
        document_type="factura",
    )
    response = client.get(
        f"/v1/emitters/{emitter['id']}/documents/{document['id']}/kude",
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "emitters.csc_required"


def test_get_kude_requires_signed_xml(client: TestClient):
    emitter = _create_emitter(client, external_id="erp-a", ruc="80024135", dv="5")
    response = client.post(
        f"/v1/emitters/{emitter['id']}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-empty",
            "idempotency_key": "idem-empty",
            "document_type": "factura",
            "payload": {"hello": "world"},
        },
    )
    assert response.status_code == 201
    document = response.json()["data"]["document"]
    response = client.get(
        f"/v1/emitters/{emitter['id']}/documents/{document['id']}/kude",
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "documents.signed_xml_not_available"


def test_get_kude_data_returns_normalized_factura(client: TestClient):
    emitter = _create_emitter(client, external_id="erp-a", ruc="80024135", dv="5")
    document = _create_document_with_signed_xml(
        client,
        emitter_id=emitter["id"],
        scenario_name="factura_b2b_iva10",
        document_type="factura",
    )
    response = client.get(
        f"/v1/emitters/{emitter['id']}/documents/{document['id']}/kude/data",
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 200, response.text
    body = response.json()["data"]["kude"]
    assert body["tipo"] == "factura_electronica"
    assert body["tipo_label"] == "KuDE de Factura Electrónica"
    assert body["ambiente"] == "test"
    assert body["ambiente_warning"]
    assert body["cdc"]["raw"].startswith("01800241355")
    assert len(body["cdc"]["groups"]) == 11
    assert body["emisor"]["ruc"] == "80024135"
    assert body["receptor"]["ruc"] == "80069563"
    assert body["receptor"]["razon_social"] == "TIPS SA"
    assert body["receptor"]["naturaleza"] == "contribuyente"
    assert body["items"][0]["valor_10"] != "0"
    assert body["totales"]["total_general_guaranies"] != "0"
    assert body["qr"]["url"].startswith("https://ekuatia.set.gov.py/consultas-test/qr?")
    assert body["qr"]["ambiente"] == "test"
    assert body["consulta_publica"]["portal_url"].endswith("/consultas-test/")
    assert body["nota_credito"] is None


def test_get_kude_data_returns_normalized_nota_credito(client: TestClient):
    emitter = _create_emitter(client, external_id="erp-a", ruc="80024135", dv="5")
    document = _create_document_with_signed_xml(
        client,
        emitter_id=emitter["id"],
        scenario_name="nc_total",
        document_type="nota_credito",
    )
    response = client.get(
        f"/v1/emitters/{emitter['id']}/documents/{document['id']}/kude/data",
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 200
    body = response.json()["data"]["kude"]
    assert body["tipo"] == "nota_credito_electronica"
    assert body["nota_credito"] is not None
    assert body["nota_credito"]["motivo_codigo"] == 1
    assert body["nota_credito"]["motivo_label"]
    assert body["documento_asociado"] is not None
    assert body["documento_asociado"]["tipo"] == "electronico"
    assert body["documento_asociado"]["cdc"]


def test_get_kude_data_returns_normalized_nota_debito(client: TestClient):
    emitter = _create_emitter(client, external_id="erp-a", ruc="80024135", dv="5")
    document = _create_document_with_signed_xml(
        client,
        emitter_id=emitter["id"],
        scenario_name="nd_recupero_costo",
        document_type="nota_debito",
    )
    response = client.get(
        f"/v1/emitters/{emitter['id']}/documents/{document['id']}/kude/data",
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 200
    body = response.json()["data"]["kude"]
    assert body["tipo"] == "nota_debito_electronica"
    assert body["nota_credito"] is None
    assert body["nota_debito"]["motivo_codigo"] == 6
    assert body["nota_debito"]["motivo_label"] == "Recupero de costo"
    assert body["documento_asociado"]["tipo"] == "electronico"


def test_get_kude_data_isolates_documents_across_emitters(client: TestClient):
    emitter_a = _create_emitter(client, external_id="erp-a", ruc="80024135", dv="5")
    emitter_b = _create_emitter(client, external_id="erp-b", ruc="80111111", dv="9")
    document = _create_document_with_signed_xml(
        client,
        emitter_id=emitter_a["id"],
        scenario_name="factura_b2b_iva10",
        document_type="factura",
    )
    response = client.get(
        f"/v1/emitters/{emitter_b['id']}/documents/{document['id']}/kude/data",
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 404


def test_get_kude_data_requires_emitter_csc(client: TestClient):
    emitter = _create_emitter(
        client,
        external_id="erp-no-csc",
        ruc="80024135",
        dv="5",
        csc=None,
        csc_id=None,
    )
    document = _create_document_with_signed_xml(
        client,
        emitter_id=emitter["id"],
        scenario_name="factura_b2b_iva10",
        document_type="factura",
    )
    response = client.get(
        f"/v1/emitters/{emitter['id']}/documents/{document['id']}/kude/data",
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "emitters.csc_required"


def test_get_kude_data_does_not_expose_csc(client: TestClient):
    emitter = _create_emitter(client, external_id="erp-a", ruc="80024135", dv="5")
    document = _create_document_with_signed_xml(
        client,
        emitter_id=emitter["id"],
        scenario_name="factura_b2b_iva10",
        document_type="factura",
    )
    response = client.get(
        f"/v1/emitters/{emitter['id']}/documents/{document['id']}/kude/data",
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 200
    raw_body = response.text
    assert _CSC not in raw_body
    # Defensive: also check that a JSON re-serialization doesn't sneak it in.
    assert _CSC not in json.dumps(response.json())


def test_get_kude_data_qr_matches_qr_generator_byte_exact(client: TestClient):
    from datetime import datetime
    from decimal import Decimal
    from xml.etree import ElementTree as ET

    emitter = _create_emitter(client, external_id="erp-a", ruc="80024135", dv="5")
    document = _create_document_with_signed_xml(
        client,
        emitter_id=emitter["id"],
        scenario_name="factura_b2b_iva10",
        document_type="factura",
    )
    response = client.get(
        f"/v1/emitters/{emitter['id']}/documents/{document['id']}/kude/data",
        headers={"X-API-Key": API_KEY},
    )
    assert response.status_code == 200
    body = response.json()["data"]["kude"]

    signed_xml = (_GOLDEN_DIR / "factura_b2b_iva10.xml").read_text(encoding="utf-8")
    ns = "http://ekuatia.set.gov.py/sifen/xsd"
    dsig = "http://www.w3.org/2000/09/xmldsig#"
    root = ET.fromstring(signed_xml.encode("utf-8"))
    de = root.find(f"{{{ns}}}DE")
    cdc = de.attrib["Id"]
    fecha_emi = datetime.fromisoformat(
        de.find(f"{{{ns}}}gDatGralOpe/{{{ns}}}dFeEmiDE").text
    )
    rec_ruc = de.find(f"{{{ns}}}gDatGralOpe/{{{ns}}}gDatRec/{{{ns}}}dRucRec").text
    g_tot = de.find(f"{{{ns}}}gTotSub")
    total_general = Decimal(g_tot.find(f"{{{ns}}}dTotGralOpe").text)
    total_iva = Decimal(g_tot.find(f"{{{ns}}}dTotIVA").text)
    items_count = len(de.find(f"{{{ns}}}gDtipDE").findall(f"{{{ns}}}gCamItem"))
    digest = root.find(
        f"{{{dsig}}}Signature/{{{dsig}}}SignedInfo/{{{dsig}}}Reference/{{{dsig}}}DigestValue"
    ).text.strip()

    expected = build_sifen_qr_url(
        cdc=cdc,
        fecha_emision=fecha_emi,
        rec_identifier=rec_ruc,
        total_general=total_general,
        total_iva=total_iva,
        cantidad_items=items_count,
        digest_value=digest,
        csc=_CSC,
        id_csc=_CSC_ID,
        ambiente="test",
    )
    assert body["qr"]["url"] == expected
