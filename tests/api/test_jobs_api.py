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
    database_url = f"sqlite:///{tmp_path / 'jobs.db'}"
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
def created_job_id(client: TestClient) -> str:
    emitter_response = client.post(
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
    emitter_id = emitter_response.json()["data"]["emitter"]["id"]

    document_response = client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-doc-1",
            "idempotency_key": "idem-1",
            "document_type": "factura",
            "payload": {"total": "100000"},
        },
    )
    return document_response.json()["data"]["job"]["id"]


def test_get_job_returns_detail(client: TestClient, created_job_id: str) -> None:
    response = client.get(
        f"/v1/jobs/{created_job_id}",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    job = response.json()["data"]["job"]
    assert job["id"] == created_job_id
    assert job["job_type"] == "document.emit"
    assert job["status"] == "queued"
