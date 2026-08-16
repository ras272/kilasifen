from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.config import get_settings
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.session import build_engine
from kilasifen.testing.database import managed_test_database_url


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    with managed_test_database_url(tmp_path=tmp_path, name="api_keys") as database_url:
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", '["secret-key"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        Base.metadata.create_all(build_engine(database_url))
        with TestClient(create_app()) as test_client:
            yield test_client


def test_protected_endpoint_requires_api_key(client: TestClient) -> None:
    response = client.get("/v1/auth/check")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.missing_api_key"


def test_protected_endpoint_rejects_invalid_api_key(client: TestClient) -> None:
    response = client.get("/v1/auth/check", headers={"X-API-Key": "wrong-key"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.invalid_api_key"


def test_protected_endpoint_accepts_valid_api_key(client: TestClient) -> None:
    response = client.get("/v1/auth/check", headers={"X-API-Key": "secret-key"})

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"authenticated": True}
    assert isinstance(body["correlation_id"], str)
