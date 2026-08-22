from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.config import get_settings
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.session import build_engine
from kilasifen.testing.database import managed_test_database_url

API_KEY = "sandbox-test-key"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    with managed_test_database_url(tmp_path=tmp_path, name="sandbox") as database_url:
        monkeypatch.setenv("KILA_SIFEN_ENVIRONMENT", "test")
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
            "external_id": "sandbox-emitter",
            "ruc": "80024135",
            "dv": "5",
            "legal_name": "KILASIFEN SANDBOX",
            "tax_environment": "test",
        },
    )
    assert response.status_code == 201
    return response.json()["data"]["emitter"]["id"]


def test_factura_accepts_typed_test_outcome_header(
    client: TestClient,
    emitter_id: str,
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={
            "X-API-Key": API_KEY,
            "X-Kila-Test-Outcome": "approved_with_observation",
        },
        json={
            "external_id": "sandbox-factura-1",
            "factura": {
                "cliente": {"ruc": "80069563-1", "razon_social": "TIPS S.A"},
                "items": [
                    {
                        "descripcion": "Servicio sandbox",
                        "cantidad": 1,
                        "precio_unitario": 1000,
                    }
                ],
            },
        },
    )

    assert response.status_code == 201
    snapshot = response.json()["data"]["document"]["payload_snapshot"]
    assert snapshot["sandbox"] == {
        "version": 1,
        "outcome": "approved_with_observation",
    }


def test_test_outcome_header_rejects_unknown_values(
    client: TestClient,
    emitter_id: str,
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={
            "X-API-Key": API_KEY,
            "X-Kila-Test-Outcome": "whatever",
        },
        json={
            "factura": {
                "cliente": {"ruc": "80069563-1", "razon_social": "TIPS S.A"},
                "items": [
                    {
                        "descripcion": "Servicio sandbox",
                        "cantidad": 1,
                        "precio_unitario": 1000,
                    }
                ],
            }
        },
    )

    assert response.status_code == 422


def test_openapi_exposes_the_sandbox_header_as_a_closed_enum(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    operation = schema["paths"][
        "/v1/emitters/{emitter_id}/documents/facturas"
    ]["post"]
    header = next(
        parameter
        for parameter in operation["parameters"]
        if parameter["name"] == "X-Kila-Test-Outcome"
    )

    assert header["in"] == "header"
    outcome_schema_name = header["schema"]["anyOf"][0]["$ref"].rsplit("/", 1)[-1]
    assert set(schema["components"]["schemas"][outcome_schema_name]["enum"]) == {
        "approved",
        "approved_with_observation",
        "rejected",
        "transport_timeout",
        "accepted_but_response_lost",
    }


def test_api_rejects_sandbox_header_outside_test_before_creating_document(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="sandbox-disabled",
    ) as database_url:
        monkeypatch.setenv("KILA_SIFEN_ENVIRONMENT", "development")
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{API_KEY}"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        monkeypatch.setenv(
            "KILA_SIFEN_ENCRYPTION_KEY",
            Fernet.generate_key().decode(),
        )
        get_settings.cache_clear()
        Base.metadata.create_all(build_engine(database_url))

        with TestClient(create_app()) as restricted_client:
            emitter = restricted_client.post(
                "/v1/emitters",
                headers={"X-API-Key": API_KEY},
                json={
                    "external_id": "restricted-emitter",
                    "ruc": "80024135",
                    "dv": "5",
                    "legal_name": "KILASIFEN RESTRICTED",
                    "tax_environment": "test",
                },
            )
            assert emitter.status_code == 201
            restricted_emitter_id = emitter.json()["data"]["emitter"]["id"]

            response = restricted_client.post(
                f"/v1/emitters/{restricted_emitter_id}/documents/facturas",
                headers={
                    "X-API-Key": API_KEY,
                    "X-Kila-Test-Outcome": "approved",
                },
                json={
                    "factura": {
                        "cliente": {
                            "ruc": "80069563-1",
                            "razon_social": "TIPS S.A",
                        },
                        "items": [
                            {
                                "descripcion": "No debe persistirse",
                                "cantidad": 1,
                                "precio_unitario": 1000,
                            }
                        ],
                    }
                },
            )

            assert response.status_code == 422
            assert response.json()["error"]["code"] == "sandbox.test_runtime_required"
            listed = restricted_client.get(
                f"/v1/emitters/{restricted_emitter_id}/documents",
                headers={"X-API-Key": API_KEY},
            )
            assert listed.json()["data"]["pagination"]["count"] == 0
