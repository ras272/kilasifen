from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.config import get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_protected_endpoint_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KILA_SIFEN_API_KEYS", '["secret-key"]')
    client = TestClient(create_app())

    response = client.get("/v1/auth/check")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.missing_api_key"


def test_protected_endpoint_rejects_invalid_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KILA_SIFEN_API_KEYS", '["secret-key"]')
    client = TestClient(create_app())

    response = client.get("/v1/auth/check", headers={"X-API-Key": "wrong-key"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.invalid_api_key"


def test_protected_endpoint_accepts_valid_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KILA_SIFEN_API_KEYS", '["secret-key"]')
    client = TestClient(create_app())

    response = client.get("/v1/auth/check", headers={"X-API-Key": "secret-key"})

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"authenticated": True}
    assert isinstance(body["correlation_id"], str)
