from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.config import get_settings
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.session import build_engine


API_KEY = "secret-key"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    database_url = f"sqlite:///{tmp_path / 'stampings.db'}"
    monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{API_KEY}"]')
    monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
    monkeypatch.setenv(
        "KILA_SIFEN_ENCRYPTION_KEY",
        Fernet.generate_key().decode(),
    )

    engine = build_engine(database_url)
    Base.metadata.create_all(engine)

    return TestClient(create_app())


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


def test_create_activate_and_list_stampings(client: TestClient, emitter_id: str) -> None:
    create_response = client.post(
        f"/v1/emitters/{emitter_id}/stampings",
        headers={"X-API-Key": API_KEY},
        json={
            "number": "80024135",
            "start_date": "2024-03-11",
            "end_date": None,
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()["data"]["stamping"]
    assert created["number"] == "80024135"
    assert created["is_active"] is False

    stamping_id = created["id"]

    activate_response = client.post(
        f"/v1/stampings/{stamping_id}/activate",
        headers={"X-API-Key": API_KEY},
    )

    assert activate_response.status_code == 200
    activated = activate_response.json()["data"]["stamping"]
    assert activated["is_active"] is True
    assert activated["status"] == "active"

    list_response = client.get(
        f"/v1/emitters/{emitter_id}/stampings",
        headers={"X-API-Key": API_KEY},
    )

    assert list_response.status_code == 200
    stampings = list_response.json()["data"]["stampings"]
    assert len(stampings) == 1
    assert stampings[0]["id"] == stamping_id


def test_create_stamping_rejects_invalid_date_window(
    client: TestClient,
    emitter_id: str,
) -> None:
    response = client.post(
        f"/v1/emitters/{emitter_id}/stampings",
        headers={"X-API-Key": API_KEY},
        json={
            "number": "80024135",
            "start_date": "2024-03-11",
            "end_date": "2024-03-10",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "stampings.invalid_date_window"
