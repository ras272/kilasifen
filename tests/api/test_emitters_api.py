from collections.abc import Iterator
from pathlib import Path

import pytest
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
    with managed_test_database_url(tmp_path=tmp_path, name="emitters") as database_url:
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{API_KEY}"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)

        engine = build_engine(database_url)
        Base.metadata.create_all(engine)

        with TestClient(create_app()) as test_client:
            yield test_client


def test_create_get_update_and_deactivate_emitter(client: TestClient) -> None:
    create_response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-ares",
            "ruc": "80024135",
            "dv": "5",
            "legal_name": "ARES PARAGUAY SRL",
            "tax_environment": "test",
            "csc": "ABCD0000000000000000000000000000",
            "csc_id": "0001",
        },
    )

    assert create_response.status_code == 201
    created_emitter = create_response.json()["data"]["emitter"]
    assert created_emitter["external_id"] == "erp-ares"
    assert created_emitter["status"] == "active"

    emitter_id = created_emitter["id"]

    get_response = client.get(
        f"/v1/emitters/{emitter_id}",
        headers={"X-API-Key": API_KEY},
    )

    assert get_response.status_code == 200
    fetched_emitter = get_response.json()["data"]["emitter"]
    assert fetched_emitter["ruc"] == "80024135"
    assert fetched_emitter["dv"] == "5"

    update_response = client.patch(
        f"/v1/emitters/{emitter_id}",
        headers={"X-API-Key": API_KEY},
        json={
            "legal_name": "ARES PARAGUAY SRL ACTUALIZADA",
            "csc_id": "0002",
        },
    )

    assert update_response.status_code == 200
    updated_emitter = update_response.json()["data"]["emitter"]
    assert updated_emitter["legal_name"] == "ARES PARAGUAY SRL ACTUALIZADA"
    assert updated_emitter["csc_id"] == "0002"

    deactivate_response = client.post(
        f"/v1/emitters/{emitter_id}/deactivate",
        headers={"X-API-Key": API_KEY},
    )

    assert deactivate_response.status_code == 200
    deactivated_emitter = deactivate_response.json()["data"]["emitter"]
    assert deactivated_emitter["status"] == "inactive"


def test_create_emitter_rejects_duplicate_external_id(client: TestClient) -> None:
    payload = {
        "external_id": "erp-ares",
        "ruc": "80024135",
        "dv": "5",
        "legal_name": "ARES PARAGUAY SRL",
        "tax_environment": "test",
        "csc": None,
        "csc_id": None,
    }

    first_response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json=payload,
    )
    assert first_response.status_code == 201

    second_response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            **payload,
            "ruc": "80111111",
            "dv": "9",
        },
    )

    assert second_response.status_code == 409
    assert second_response.json()["error"]["code"] == "emitters.external_id_conflict"


def test_get_emitter_health_returns_operational_snapshot(client: TestClient) -> None:
    create_response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-health",
            "ruc": "81234123",
            "dv": "1",
            "legal_name": "EMITTER HEALTH SA",
            "tax_environment": "test",
            "csc": None,
            "csc_id": None,
        },
    )
    emitter_id = create_response.json()["data"]["emitter"]["id"]
    client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-health-doc-1",
            "idempotency_key": "idem-health-doc-1",
            "document_type": "factura",
            "payload": {"generated_xml": "<rDE><DE Id='H1'/></rDE>", "doc_id": "H1"},
        },
    )

    response = client.get(
        f"/v1/emitters/{emitter_id}/health",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    health = response.json()["data"]["health"]
    assert health["emitter_id"] == emitter_id
    assert health["emitter_status"] == "active"
    assert health["has_active_certificate"] is False
    assert health["has_active_stamping"] is False
    assert health["last_document_id"] is not None
