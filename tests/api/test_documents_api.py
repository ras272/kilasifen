from collections.abc import Iterator
import logging
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.config import get_settings
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.session import build_engine
from kilasifen.testing.database import managed_test_database_url


API_KEY = "secret-key"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    with managed_test_database_url(tmp_path=tmp_path, name="documents") as database_url:
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{API_KEY}"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        monkeypatch.setenv(
            "KILA_SIFEN_ENCRYPTION_KEY",
            Fernet.generate_key().decode(),
        )

        engine = build_engine(database_url)
        Base.metadata.create_all(engine)

        with TestClient(create_app()) as test_client:
            yield test_client


@pytest.fixture
def emitter_id(client: TestClient) -> str:
    response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-ares",
            "ruc": "80024135",
            "dv": "5",
            "legal_name": "ARES PARAGUAY SRL",
            "tax_environment": "test",
            "csc": None,
            "csc_id": None,
        },
    )
    assert response.status_code == 201
    return response.json()["data"]["emitter"]["id"]


@pytest.fixture
def second_emitter_id(client: TestClient) -> str:
    response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-ares-2",
            "ruc": "80111111",
            "dv": "9",
            "legal_name": "OTRO EMISOR SA",
            "tax_environment": "test",
            "csc": None,
            "csc_id": None,
        },
    )
    assert response.status_code == 201
    return response.json()["data"]["emitter"]["id"]


def test_create_document_returns_document_and_job(client: TestClient, emitter_id: str) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-doc-1",
            "idempotency_key": "idem-1",
            "document_type": "factura",
            "payload": {"total": "100000"},
        },
    )

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["document"]["external_id"] == "erp-doc-1"
    assert body["document"]["internal_status"] == "queued"
    assert body["job"]["job_type"] == "document.emit"
    assert body["job"]["status"] == "queued"


def test_create_document_is_idempotent_for_same_key(client: TestClient, emitter_id: str) -> None:
    payload = {
        "external_id": "erp-doc-1",
        "idempotency_key": "idem-1",
        "document_type": "factura",
        "payload": {"total": "100000"},
    }

    first_response = client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json=payload,
    )
    second_response = client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json=payload,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert (
        second_response.json()["data"]["document"]["id"]
        == first_response.json()["data"]["document"]["id"]
    )
    assert (
        second_response.json()["data"]["job"]["id"]
        == first_response.json()["data"]["job"]["id"]
    )


def test_create_factura_typed_endpoint_returns_document_and_job(
    client: TestClient,
    emitter_id: str,
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-factura-1",
            "idempotency_key": "idem-factura-1",
            "factura": {
                "generated_xml": "<rDE xmlns='http://ekuatia.set.gov.py/sifen/xsd'><DE Id='01800123450001001000000012026010112345678901'/></rDE>",
                "doc_id": "01800123450001001000000012026010112345678901",
                "establecimiento": 1,
                "punto": "001",
                "numero": 10,
                "fecha": "2026-04-25T10:00:00",
                "cliente": {"ruc": "80069563-1", "razonSocial": "TIPS S.A"},
                "items": [{"descripcion": "Producto", "cantidad": 1, "precioUnitario": 1000}],
            },
        },
    )

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["document"]["document_type"] == "factura"
    assert body["job"]["job_type"] == "document.emit"


def test_create_nota_credito_typed_endpoint_returns_document_and_job(
    client: TestClient,
    emitter_id: str,
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/notas-credito",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-nc-1",
            "idempotency_key": "idem-nc-1",
            "nota_credito": {
                "generated_xml": "<rDE xmlns='http://ekuatia.set.gov.py/sifen/xsd'><DE Id='01800123450001001000000512026010112345678901'/></rDE>",
                "doc_id": "01800123450001001000000512026010112345678901",
                "documento_asociado": {"cdc": "01800123450001001000000012026010112345678901"},
                "items": [{"descripcion": "Descuento", "cantidad": 1, "precioUnitario": 500}],
            },
        },
    )

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["document"]["document_type"] == "nota_credito"
    assert body["job"]["job_type"] == "document.emit"


def test_create_typed_document_requires_xml_or_signed_xml(
    client: TestClient,
    emitter_id: str,
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-factura-2",
            "idempotency_key": "idem-factura-2",
            "factura": {
                "doc_id": "01800123450001001000000012026010112345678901",
            },
        },
    )

    assert response.status_code == 422


def test_create_factura_typed_endpoint_without_xml_is_accepted(
    client: TestClient,
    emitter_id: str,
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-factura-3",
            "idempotency_key": "idem-factura-3",
            "factura": {
                "numero": 1003,
                "fecha": "2026-04-25T10:00:00",
                "cliente": {"ruc": "80069563-1", "razonSocial": "TIPS S.A"},
                "items": [
                    {
                        "descripcion": "Producto",
                        "cantidad": 1,
                        "precioUnitario": 1000,
                        "iva": 10,
                    }
                ],
            },
        },
    )

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["document"]["document_type"] == "factura"
    assert body["document"]["payload_snapshot"]["generated_xml"] is None


def test_list_documents_returns_only_requested_emitter_documents(
    client: TestClient,
    emitter_id: str,
    second_emitter_id: str,
) -> None:
    response_a = client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-doc-a-1",
            "idempotency_key": "idem-a-1",
            "document_type": "factura",
            "payload": {"generated_xml": "<rDE><DE Id='A1'/></rDE>", "doc_id": "A1"},
        },
    )
    assert response_a.status_code == 201
    response_b = client.post(
        f"/v1/emitters/{second_emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-doc-b-1",
            "idempotency_key": "idem-b-1",
            "document_type": "factura",
            "payload": {"generated_xml": "<rDE><DE Id='B1'/></rDE>", "doc_id": "B1"},
        },
    )
    assert response_b.status_code == 201

    listed = client.get(
        f"/v1/emitters/{emitter_id}/documents?limit=10&offset=0",
        headers={"X-API-Key": API_KEY},
    )

    assert listed.status_code == 200
    body = listed.json()["data"]
    assert body["pagination"]["count"] == 1
    assert body["documents"][0]["document"]["external_id"] == "erp-doc-a-1"
    assert body["documents"][0]["document"]["emitter_id"] == emitter_id


def test_get_document_xml_returns_signed_or_generated_xml(
    client: TestClient,
    emitter_id: str,
) -> None:
    created = client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-doc-xml",
            "idempotency_key": "idem-xml",
            "document_type": "factura",
            "payload": {
                "generated_xml": "<rDE xmlns='http://ekuatia.set.gov.py/sifen/xsd'><DE Id='XML1'/></rDE>",
                "doc_id": "XML1",
            },
        },
    )
    document_id = created.json()["data"]["document"]["id"]

    response = client.get(
        f"/v1/emitters/{emitter_id}/documents/{document_id}/xml",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "<rDE" in response.text


def test_get_document_xml_returns_not_found_for_other_emitter_document(
    client: TestClient,
    emitter_id: str,
    second_emitter_id: str,
) -> None:
    created = client.post(
        f"/v1/emitters/{second_emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-doc-xml-b",
            "idempotency_key": "idem-xml-b",
            "document_type": "factura",
            "payload": {
                "generated_xml": "<rDE xmlns='http://ekuatia.set.gov.py/sifen/xsd'><DE Id='XMLB'/></rDE>",
                "doc_id": "XMLB",
            },
        },
    )
    document_id = created.json()["data"]["document"]["id"]

    response = client.get(
        f"/v1/emitters/{emitter_id}/documents/{document_id}/xml",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 404


def test_create_typed_document_ignores_client_number_and_logs_warning(
    client: TestClient,
    emitter_id: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="kilasifen.application.documents.service")
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-factura-numbering-warning",
            "idempotency_key": "idem-factura-numbering-warning",
            "factura": {
                "numero": 999,
                "fecha": "2026-04-25T10:00:00",
                "cliente": {"ruc": "80069563-1", "razonSocial": "TIPS S.A"},
                "items": [{"descripcion": "Producto", "cantidad": 1, "precioUnitario": 1000}],
            },
        },
    )

    assert response.status_code == 201
    document = response.json()["data"]["document"]
    assert document["document_number"] == 1
    assert document["payload_snapshot"]["typed_contract"]["payload"]["numero"] == 1
    assert any(
        record.message == "documents.numbering.client_number_ignored"
        for record in caplog.records
    )
