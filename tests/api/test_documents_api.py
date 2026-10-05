from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.api.deps import get_fiscal_clock
from kilasifen.config import get_settings
from kilasifen.domain.common.paraguay_time import PARAGUAY_TZ
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.session import build_engine
from kilasifen.testing.database import managed_test_database_url
from kilasifen.testing.fiscal_profiles import fictional_fiscal_profile_payload
from tests._raw_xml import (
    raw_document_payload,
    unsigned_rde,
    unsigned_rde_with_extra_child,
)

API_KEY = "secret-key"
_FISCAL_NOW = datetime(2026, 4, 25, 12, 0, 0, tzinfo=PARAGUAY_TZ)
_SIFEN_NS = "http://ekuatia.set.gov.py/sifen/xsd"
_FORGED_DE = f"<DE xmlns='{_SIFEN_NS}' Id='FORGED1'><anything>x</anything></DE>"


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

        app = create_app()
        # The typed payloads below are dated 2026-04-25; dFeEmiDE must be
        # inside the 720 h / 120 h window of that moment (1150/1151).
        app.dependency_overrides[get_fiscal_clock] = lambda: lambda: _FISCAL_NOW
        with TestClient(app) as test_client:
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
            "fiscal_profile": fictional_fiscal_profile_payload(),
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
            "dv": "0",
            "legal_name": "OTRO EMISOR SA",
            "tax_environment": "test",
            "csc": None,
            "csc_id": None,
            "fiscal_profile": fictional_fiscal_profile_payload(),
        },
    )
    assert response.status_code == 201
    return response.json()["data"]["emitter"]["id"]


def test_create_document_returns_document_and_job(
    client: TestClient, emitter_id: str
) -> None:
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


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"signed_xml": "<rDE/>"}, "documents.raw.signed_xml_not_allowed"),
        (
            {"generated_xml": "<rDE><DE Id='A1'/></rDE>", "doc_id": "A1"},
            "documents.raw.generated_xml_root_not_rde",
        ),
        (
            {
                "generated_xml": (
                    f"<rDE xmlns='{_SIFEN_NS}'><dVerFor>150</dVerFor>"
                    "<DE Id='A1'/></rDE>"
                ),
                "doc_id": "A1",
            },
            "documents.raw.generated_xml_invalid_schema",
        ),
        (
            {
                "generated_xml": unsigned_rde_with_extra_child(_FORGED_DE),
                "doc_id": "FORGED1",
            },
            "documents.raw.generated_xml_unexpected_element",
        ),
        (
            {"generated_xml": unsigned_rde()[0], "doc_id": "FORGED1"},
            "documents.raw.doc_id_mismatch",
        ),
        (
            {
                "typed_contract": {
                    "contract": "factura_v1",
                    "payload": {"signed_xml": "<rDE/>"},
                }
            },
            "documents.raw.signed_xml_not_allowed",
        ),
    ],
)
def test_raw_document_rejects_xml_the_platform_must_not_sign(
    client: TestClient,
    emitter_id: str,
    payload: dict,
    code: str,
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-raw-xml",
            "idempotency_key": "idem-raw-xml",
            "document_type": "factura",
            "payload": payload,
        },
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == code
    assert error["category"] == "validation"

    listed = client.get(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
    )
    assert listed.json()["data"]["pagination"]["count"] == 0


def test_raw_document_accepts_an_unsigned_xsd_valid_rde(
    client: TestClient,
    emitter_id: str,
) -> None:
    payload = raw_document_payload()

    response = client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-raw-valid",
            "idempotency_key": "idem-raw-valid",
            "document_type": "factura",
            "payload": payload,
        },
    )

    assert response.status_code == 201
    snapshot = response.json()["data"]["document"]["payload_snapshot"]
    assert snapshot["generated_xml"] == payload["generated_xml"]
    assert "signed_xml" not in snapshot


def test_create_document_is_idempotent_for_same_key(
    client: TestClient, emitter_id: str
) -> None:
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


@pytest.mark.parametrize(
    ("changes", "mismatched_parameters"),
    [
        ({"payload": {"total": "200000"}}, ["payload"]),
        ({"document_type": "nota_credito"}, ["document_type"]),
        ({"external_id": "erp-doc-2"}, ["external_id"]),
    ],
)
def test_create_document_rejects_idempotency_key_reuse_for_different_intent(
    client: TestClient,
    emitter_id: str,
    changes: dict,
    mismatched_parameters: list[str],
) -> None:
    original = {
        "external_id": "erp-doc-1",
        "idempotency_key": "idem-conflict-1",
        "document_type": "factura",
        "payload": {"total": "100000"},
    }
    first_response = client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json=original,
    )

    conflicting = {**original, **changes}
    conflict_response = client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json=conflicting,
    )

    assert first_response.status_code == 201
    assert conflict_response.status_code == 409
    error = conflict_response.json()["error"]
    assert error["code"] == "documents.idempotency_key_conflict"
    assert error["category"] == "conflict"
    assert error["details"] == {
        "existing_document_id": first_response.json()["data"]["document"]["id"],
        "mismatched_parameters": mismatched_parameters,
    }


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
                "establecimiento": 1,
                "punto": "001",
                "numero": 10,
                "fecha": "2026-04-25T10:00:00",
                "cliente": {
                    "ruc": "80025298-5",
                    "razonSocial": "CLIENTE FICTICIO SA",
                    "tipo_contribuyente": 2,
                },
                "items": [
                    {"descripcion": "Producto", "cantidad": 1, "precioUnitario": 1000}
                ],
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
                "cliente": {
                    "ruc": "80025298-5",
                    "razonSocial": "CLIENTE FICTICIO SA",
                    "tipo_contribuyente": 2,
                },
                "documento_asociado": {
                    "cdc": "01800123450001001000000012026010112345678901"
                },
                "items": [
                    {"descripcion": "Descuento", "cantidad": 1, "precioUnitario": 500}
                ],
            },
        },
    )

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["document"]["document_type"] == "nota_credito"
    assert body["job"]["job_type"] == "document.emit"


def test_create_nota_debito_typed_endpoint_returns_document_and_job(
    client: TestClient,
    emitter_id: str,
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/notas-debito",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-nd-1",
            "idempotency_key": "idem-nd-1",
            "nota_debito": {
                "motivo_emision": "recupero_costo",
                "cliente": {
                    "ruc": "80025298-5",
                    "razonSocial": "CLIENTE FICTICIO SA",
                    "tipo_contribuyente": 2,
                },
                "documento_asociado": {
                    "cdc": "01800123450001001000000012026010112345678901"
                },
                "items": [
                    {
                        "descripcion": "Recupero de costo",
                        "cantidad": 1,
                        "precioUnitario": 500,
                    }
                ],
            },
        },
    )

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["document"]["document_type"] == "nota_debito"
    assert body["document"]["payload_snapshot"]["typed_contract"]["contract"] == (
        "nota_debito_v1"
    )
    assert body["job"]["job_type"] == "document.emit"


def test_create_typed_document_requires_business_payload(
    client: TestClient,
    emitter_id: str,
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-factura-2",
            "idempotency_key": "idem-factura-2",
            "factura": {},
        },
    )

    assert response.status_code == 422


def test_create_typed_document_rejects_caller_supplied_xml(
    client: TestClient,
    emitter_id: str,
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={
            "factura": {
                "generated_xml": "<attacker-controlled/>",
                "cliente": {"ruc": "80025298-5"},
                "items": [
                    {"descripcion": "Producto", "cantidad": 1, "precioUnitario": 1}
                ],
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
                "cliente": {
                    "ruc": "80025298-5",
                    "razonSocial": "CLIENTE FICTICIO SA",
                    "tipo_contribuyente": 2,
                },
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


@pytest.mark.parametrize(
    "factura",
    [
        {
            "cliente": {"naturaleza": 2, "nombre": "CLIENTE SIN DOCUMENTO"},
            "items": [
                {"descripcion": "Producto", "cantidad": 1, "precioUnitario": 1000}
            ],
        },
        {
            "cliente": {
                    "ruc": "80025298-5",
                    "razonSocial": "CLIENTE FICTICIO SA",
                    "tipo_contribuyente": 2,
                },
            "items": [
                {
                    "descripcion": "Neto negativo",
                    "cantidad": 1,
                    "precioUnitario": 1000,
                    "descuento_particular": 1001,
                }
            ],
        },
        {
            "moneda": "PYG",
            "condicion_tipo_cambio": 1,
            "tipo_cambio": 7300,
            "cliente": {
                    "ruc": "80025298-5",
                    "razonSocial": "CLIENTE FICTICIO SA",
                    "tipo_contribuyente": 2,
                },
            "items": [
                {"descripcion": "Producto", "cantidad": 1, "precioUnitario": 1000}
            ],
        },
        {
            "cliente": {
                    "ruc": "80025298-5",
                    "razonSocial": "CLIENTE FICTICIO SA",
                    "tipo_contribuyente": 2,
                },
            "condicion_operacion": {
                "tipo": "contado",
                "formas_pago": [{"tipo": "cheque", "monto": 1000}],
            },
            "items": [
                {"descripcion": "Producto", "cantidad": 1, "precioUnitario": 1000}
            ],
        },
    ],
    ids=[
        "receiver-identity",
        "negative-net-item",
        "pyg-exchange-rate",
        "incomplete-cheque",
    ],
)
def test_create_factura_rejects_invalid_fiscal_contract_before_queueing(
    client: TestClient,
    emitter_id: str,
    factura: dict,
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={"factura": factura},
    )

    assert response.status_code == 422


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
            "payload": raw_document_payload(),
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
            "payload": raw_document_payload(),
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


def test_get_document_returns_document_and_associated_job(
    client: TestClient,
    emitter_id: str,
) -> None:
    created = client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-doc-detail",
            "idempotency_key": "idem-detail",
            "document_type": "factura",
            "payload": raw_document_payload(),
        },
    )
    document_id = created.json()["data"]["document"]["id"]

    response = client.get(
        f"/v1/emitters/{emitter_id}/documents/{document_id}",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["document"]["id"] == document_id
    assert body["job"]["related_entity_id"] == document_id
    assert body["job"]["job_type"] == "document.emit"


def test_get_document_returns_not_found_for_other_emitter_document(
    client: TestClient,
    emitter_id: str,
    second_emitter_id: str,
) -> None:
    created = client.post(
        f"/v1/emitters/{second_emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-doc-detail-b",
            "idempotency_key": "idem-detail-b",
            "document_type": "factura",
            "payload": raw_document_payload(),
        },
    )
    document_id = created.json()["data"]["document"]["id"]

    response = client.get(
        f"/v1/emitters/{emitter_id}/documents/{document_id}",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "documents.not_found"


def test_get_document_requires_valid_api_key(
    client: TestClient,
    emitter_id: str,
) -> None:
    created = client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-doc-auth",
            "idempotency_key": "idem-auth",
            "document_type": "factura",
            "payload": raw_document_payload(),
        },
    )
    document_id = created.json()["data"]["document"]["id"]

    response = client.get(
        f"/v1/emitters/{emitter_id}/documents/{document_id}",
        headers={"X-API-Key": "wrong-key"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.invalid_api_key"


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=101", "offset=-1"],
)
def test_list_documents_rejects_unbounded_pagination(
    client: TestClient,
    emitter_id: str,
    query: str,
) -> None:
    response = client.get(
        f"/v1/emitters/{emitter_id}/documents?{query}",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 422


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
            "payload": raw_document_payload(),
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
            "payload": raw_document_payload(),
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warning = Mock()
    monkeypatch.setattr(
        "kilasifen.application.documents.service.logger.warning",
        warning,
    )
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-factura-numbering-warning",
            "idempotency_key": "idem-factura-numbering-warning",
            "factura": {
                "numero": 999,
                "fecha": "2026-04-25T10:00:00",
                "cliente": {
                    "ruc": "80025298-5",
                    "razonSocial": "CLIENTE FICTICIO SA",
                    "tipo_contribuyente": 2,
                },
                "items": [
                    {"descripcion": "Producto", "cantidad": 1, "precioUnitario": 1000}
                ],
            },
        },
    )

    assert response.status_code == 201
    document = response.json()["data"]["document"]
    assert document["document_number"] == 1
    assert document["payload_snapshot"]["typed_contract"]["payload"]["numero"] == 1
    warning.assert_called_once()
    assert warning.call_args.args[0] == "documents.numbering.client_number_ignored"


def test_typed_document_requires_the_emitter_fiscal_profile(
    client: TestClient,
) -> None:
    created = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "ruc": "44444401",
            "dv": "7",
            "legal_name": "EMISOR SIN PERFIL SA",
            "tax_environment": "test",
        },
    )
    emitter_without_profile = created.json()["data"]["emitter"]["id"]

    response = client.post(
        f"/v1/emitters/{emitter_without_profile}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={
            "factura": {
                "cliente": {
                    "ruc": "80025298-5",
                    "razonSocial": "CLIENTE FICTICIO SA",
                    "tipo_contribuyente": 2,
                },
                "items": [
                    {"descripcion": "Producto", "cantidad": 1, "precioUnitario": 1000}
                ],
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "emitters.fiscal_profile_required"


@pytest.mark.parametrize(
    ("factura_changes", "field"),
    [
        ({"emisor": {"ruc": "80111111-0"}}, "emisor.ruc"),
        ({"emisor": {"razon_social": "OTRA RAZON SOCIAL"}}, "emisor.razon_social"),
        ({"tipo_contribuyente": 1}, "tipo_contribuyente"),
    ],
)
def test_typed_document_cannot_change_the_emitter_identity(
    client: TestClient,
    emitter_id: str,
    factura_changes: dict,
    field: str,
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={
            "factura": {
                "cliente": {
                    "ruc": "80025298-5",
                    "razonSocial": "CLIENTE FICTICIO SA",
                    "tipo_contribuyente": 2,
                },
                "items": [
                    {"descripcion": "Producto", "cantidad": 1, "precioUnitario": 1000}
                ],
                **factura_changes,
            },
        },
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "documents.emisor.identity_mismatch"
    assert error["details"]["field"] == field


@pytest.mark.parametrize(
    ("fecha", "code"),
    [
        ("2026-03-25T11:59:59", "documents.fecha_emision.too_old"),  # 1150
        ("2026-04-30T12:00:01", "documents.fecha_emision.too_far_ahead"),  # 1151
        ("2018-11-20T10:00:00", "documents.fecha_emision.before_sifen_launch"),
        ("25/04/2026", "documents.fecha_emision.invalid"),
    ],
)
def test_typed_document_outside_the_emission_window_is_rejected(
    client: TestClient, emitter_id: str, fecha: str, code: str
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={
            "factura": {
                "fecha_emision": fecha,
                "cliente": {
                    "ruc": "80025298-5",
                    "razonSocial": "CLIENTE FICTICIO SA",
                    "tipo_contribuyente": 2,
                },
                "items": [
                    {"descripcion": "Producto", "cantidad": 1, "precioUnitario": 1000}
                ],
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_typed_document_far_from_transmission_is_created_with_a_warning(
    client: TestClient, emitter_id: str
) -> None:
    # 130 h before the clock: inside 720 h, but SIFEN approves it with
    # observation 1005 (MT v150 §6.2.1).
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={
            "factura": {
                "fecha_emision": "2026-04-20T02:00:00",
                "cliente": {
                    "ruc": "80025298-5",
                    "razonSocial": "CLIENTE FICTICIO SA",
                    "tipo_contribuyente": 2,
                },
                "items": [
                    {"descripcion": "Producto", "cantidad": 1, "precioUnitario": 1000}
                ],
            },
        },
    )

    assert response.status_code == 201
    document = response.json()["data"]["document"]
    assert document["fiscal_warnings"] == [
        "documents.transmission.emission_far_from_now"
    ]
    fetched = client.get(
        f"/v1/emitters/{emitter_id}/documents/{document['id']}",
        headers={"X-API-Key": API_KEY},
    ).json()["data"]["document"]
    assert fetched["fiscal_warnings"] == document["fiscal_warnings"]


_ITEMS = [{"descripcion": "Producto", "cantidad": 1, "precioUnitario": 1000}]


@pytest.mark.parametrize(
    ("cliente", "message"),
    [
        (
            {"ruc": "80025298-5", "razon_social": "CLIENTE FICTICIO SA"},
            "documents.cliente.tipo_contribuyente_required",
        ),
        (
            {
                "ruc": "80025298-4",
                "razon_social": "CLIENTE FICTICIO SA",
                "tipo_contribuyente": 2,
            },
            "documents.cliente.dv_mismatch",
        ),
        (
            {
                "naturaleza": 2,
                "tipo_operacion": 1,
                "tipo_documento_identidad": 1,
                "numero_documento_identidad": "1234567",
                "nombre": "PERSONA FICTICIA",
            },
            "documents.cliente.tipo_operacion_not_allowed",
        ),
        (
            {
                "naturaleza": 2,
                "tipo_operacion": 4,
                "tipo_documento_identidad": 2,
                "numero_documento_identidad": "X1234567",
                "nombre": "FOREIGN CUSTOMER LLC",
                "pais_codigo": "ARG",
            },
            "documents.cliente.direccion_required",
        ),
    ],
)
def test_typed_document_receiver_rules_answer_422(
    client: TestClient, emitter_id: str, cliente: dict, message: str
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={"factura": {"cliente": cliente, "items": _ITEMS}},
    )

    assert response.status_code == 422
    assert message in response.text


def test_nota_credito_refuses_an_innominado_receiver(
    client: TestClient, emitter_id: str
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/notas-credito",
        headers={"X-API-Key": API_KEY},
        json={
            "nota_credito": {
                "cliente": {
                    "naturaleza": 2,
                    "tipo_operacion": 2,
                    "tipo_documento_identidad": 5,
                },
                "documento_asociado": {
                    "cdc": "01800123450001001000000012026010112345678901"
                },
                "items": _ITEMS,
            },
        },
    )

    assert response.status_code == 422
    assert "documents.cliente.innominado_not_allowed" in response.text


def test_b2g_invoice_without_public_procurement_data_is_accepted(
    client: TestClient, emitter_id: str
) -> None:
    # NT 26: gCompPub is optional in B2G.
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={
            "factura": {
                "cliente": {
                    "ruc": "80025298-5",
                    "razon_social": "ENTIDAD PUBLICA FICTICIA",
                    "tipo_contribuyente": 2,
                    "tipo_operacion": 3,
                },
                "items": _ITEMS,
            },
        },
    )

    assert response.status_code == 201


def test_generation_responsible_type_9_needs_its_description(
    client: TestClient, emitter_id: str
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={
            "factura": {
                "emisor": {
                    "responsable_generacion": {
                        "tipo_documento": 9,
                        "numero_documento": "LC-1",
                        "nombre": "RESPONSABLE FICTICIO",
                        "cargo": "CAJERO",
                    }
                },
                "cliente": {
                    "ruc": "80025298-5",
                    "razon_social": "CLIENTE FICTICIO SA",
                    "tipo_contribuyente": 2,
                },
                "items": _ITEMS,
            },
        },
    )

    assert response.status_code == 422


#: Fictional receiver (DNIT Guia de Mejores Practicas example, DV 5).
_FICTIONAL_CLIENT = {
    "ruc": "80025298-5",
    "razon_social": "CLIENTE FICTICIO SA",
    "tipo_contribuyente": 2,
}

_USD = {"moneda": "USD", "condicion_tipo_cambio": 1, "tipo_cambio": "7300"}


def _gravado(**changes) -> dict:
    item = {"descripcion": "Producto", "cantidad": 1, "precio_unitario": 1000}
    item.update(changes)
    return item


@pytest.mark.parametrize("moneda", ["XYZ", "BMD"])
def test_typed_document_currency_must_be_an_official_iso_code(
    client: TestClient, emitter_id: str, moneda: str
) -> None:
    # 1206/1555: D016/E610 are the official name of the code (Monedas_v150);
    # BMD's name does not fit the 20 characters of the description.
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={
            "factura": {
                "cliente": dict(_FICTIONAL_CLIENT),
                "items": [_gravado()],
                "moneda": moneda,
                "condicion_tipo_cambio": 1,
                "tipo_cambio": "7300",
            }
        },
    )

    assert response.status_code == 422
    assert "ISO 4217" in response.text


def test_typed_factura_accepts_rounding_and_a_global_discount(
    client: TestClient, emitter_id: str
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={
            "factura": {
                "cliente": dict(_FICTIONAL_CLIENT),
                "items": [_gravado(precio_unitario=107437)],
                "porcentaje_descuento_global": "10",
                "redondeo": "multiplo_50",
            }
        },
    )

    assert response.status_code == 201
    payload = response.json()["data"]["document"]["payload_snapshot"]
    typed = payload["typed_contract"]["payload"]
    assert typed["redondeo"] == "multiplo_50"
    assert typed["porcentaje_descuento_global"] == "10"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"items": [_gravado(afectacion="gravado_parcial")]},
            "documents.items.proporcion_gravada_required",
        ),
        (
            {"items": [_gravado(afectacion="exento", tasa=0, proporcion_gravada=100)]},
            "documents.items.proporcion_gravada_invalid",
        ),
        (
            {"items": [_gravado(descuento_global=100)]},
            "documents.items.descuento_global_mismatch",
        ),
        (
            {
                "items": [_gravado(precio_unitario="100.49")],
                "redondeo": "multiplo_50",
                **_USD,
            },
            "documents.redondeo.only_pyg",
        ),
        (
            {"items": [_gravado(precio_unitario=30)], "redondeo": "multiplo_50"},
            "documents.redondeo.total_below_50",
        ),
        (
            {
                "items": [_gravado()],
                "condicion_operacion": {
                    "tipo": "contado",
                    "formas_pago": [{"tipo": "efectivo", "monto": 500}],
                },
            },
            "documents.condicion_operacion.formas_pago.total_mismatch",
        ),
        (
            {
                "items": [_gravado()],
                "condicion_operacion": {
                    "tipo": "contado",
                    "formas_pago": [
                        {"tipo": "efectivo", "monto": 1, "moneda": "USD"}
                    ],
                },
            },
            "documents.condicion_operacion.formas_pago.tipo_cambio_required",
        ),
        (
            {
                "items": [_gravado()],
                "condicion_operacion": {
                    "tipo": "credito",
                    "credito": {
                        "tipo": "plazo",
                        "descripcion": "30 dias",
                        "monto_entrega_inicial": 100,
                    },
                },
            },
            "documents.condicion_operacion.credito.formas_pago_required",
        ),
        (
            {"items": [_gravado()], "tipo_impuesto": 2},
            "documents.tipo_impuesto.isc_not_supported",
        ),
    ],
    ids=[
        "partial-without-proportion",
        "exempt-proportion-100",
        "global-discount-without-percentage",
        "rounding-foreign-currency",
        "rounding-under-50",
        "contado-payments-mismatch",
        "foreign-payment-without-rate",
        "initial-delivery-without-payments",
        "isc",
    ],
)
def test_typed_document_amount_rules_answer_422(
    client: TestClient, emitter_id: str, changes: dict, message: str
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": API_KEY},
        json={"factura": {"cliente": dict(_FICTIONAL_CLIENT), **changes}},
    )

    assert response.status_code == 422
    assert message in response.text
