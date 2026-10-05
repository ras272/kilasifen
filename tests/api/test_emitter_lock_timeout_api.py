"""A busy emitter lock answers a retryable 503 instead of waiting forever."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.config import get_settings
from kilasifen.domain.common.errors import ServiceUnavailableError
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.repositories.emitters import (
    SqlAlchemyEmitterRepository,
)
from kilasifen.infrastructure.db.session import build_engine
from kilasifen.testing.database import managed_test_database_url

_API_KEY = "emitter-lock-admin"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client_and_emitter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[tuple[TestClient, str]]:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="emitter_lock_timeout_api",
    ) as database_url:
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{_API_KEY}"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
        Base.metadata.create_all(build_engine(database_url))

        with TestClient(create_app()) as client:
            created = client.post(
                "/v1/emitters",
                headers={"X-API-Key": _API_KEY},
                json={
                    "external_id": "lock-timeout-control",
                    "ruc": "80024135",
                    "dv": "5",
                    "legal_name": "EMISOR FICTICIO SA",
                    "tax_environment": "test",
                },
            )
            assert created.status_code == 201
            yield client, created.json()["data"]["emitter"]["id"]


def test_document_creation_maps_emitter_lock_timeout_to_503(
    client_and_emitter: tuple[TestClient, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, emitter_id = client_and_emitter

    def busy_emitter(self, emitter_id: str) -> str | None:
        del self, emitter_id
        raise ServiceUnavailableError("emitters.lock_timeout")

    monkeypatch.setattr(
        SqlAlchemyEmitterRepository, "get_status_for_update", busy_emitter
    )

    response = client.post(
        f"/v1/emitters/{emitter_id}/documents/facturas",
        headers={"X-API-Key": _API_KEY},
        json={
            "idempotency_key": "lock-timeout-document",
            "factura": {
                "cliente": {
                    "ruc": "80025298-5",
                    "razon_social": "CLIENTE FICTICIO",
                    "tipo_contribuyente": 2,
                },
                "items": [
                    {"descripcion": "Servicio", "cantidad": 1, "precioUnitario": 1}
                ],
            },
        },
    )

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "emitters.lock_timeout"
    assert error["category"] == "service_unavailable"
