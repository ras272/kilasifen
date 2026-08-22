from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from kilasifen.api.app import create_app
from kilasifen.config import get_settings
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.models import ApiKeyModel
from kilasifen.infrastructure.db.session import build_engine, session_scope
from kilasifen.security import key_prefix, verify_api_key
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


def test_replaced_bootstrap_key_is_rejected_before_replacement_is_used(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_key = "shared-prefix-old-bootstrap"
    replacement_key = "shared-prefix-new-bootstrap"
    assert key_prefix(old_key) == key_prefix(replacement_key)
    monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{old_key}"]')
    get_settings.cache_clear()

    assert (
        client.get("/v1/auth/check", headers={"X-API-Key": old_key}).status_code == 200
    )
    consumer = client.post(
        "/v1/admin/consumers",
        headers={"X-API-Key": old_key},
        json={"name": "Rotation control tenant"},
    )
    assert consumer.status_code == 201
    issued = client.post(
        f"/v1/admin/consumers/{consumer.json()['data']['consumer']['id']}/credentials",
        headers={"X-API-Key": old_key},
        json={"name": "tenant-key", "scopes": ["tenant:read"]},
    )
    assert issued.status_code == 201
    tenant_key = issued.json()["data"]["credential"]["api_key"]

    with session_scope(client.app.state.session_factory) as session:
        persisted = session.scalar(
            select(ApiKeyModel).where(ApiKeyModel.name == "bootstrap-0")
        )
        assert persisted is not None
        assert persisted.status == "active"
        assert verify_api_key(old_key, persisted.key_hash)

    monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{replacement_key}"]')
    get_settings.cache_clear()

    removed = client.get("/v1/auth/check", headers={"X-API-Key": old_key})
    assert removed.status_code == 401
    assert removed.json()["error"]["code"] == "auth.invalid_api_key"
    assert (
        client.get("/v1/auth/check", headers={"X-API-Key": tenant_key}).status_code
        == 200
    )
    assert (
        client.get("/v1/auth/check", headers={"X-API-Key": replacement_key}).status_code
        == 200
    )


def test_reordered_bootstrap_keys_remain_valid_but_removed_key_is_rejected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_key = "shared-admin-first-bootstrap"
    second_key = "shared-admin-second-bootstrap"
    assert key_prefix(first_key) == key_prefix(second_key)
    monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{first_key}","{second_key}"]')
    get_settings.cache_clear()
    assert (
        client.get("/v1/auth/check", headers={"X-API-Key": first_key}).status_code
        == 200
    )
    assert (
        client.get("/v1/auth/check", headers={"X-API-Key": second_key}).status_code
        == 200
    )

    monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{second_key}","{first_key}"]')
    get_settings.cache_clear()
    assert (
        client.get("/v1/auth/check", headers={"X-API-Key": first_key}).status_code
        == 200
    )
    assert (
        client.get("/v1/auth/check", headers={"X-API-Key": second_key}).status_code
        == 200
    )

    monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{second_key}"]')
    get_settings.cache_clear()
    removed = client.get("/v1/auth/check", headers={"X-API-Key": first_key})
    assert removed.status_code == 401
    assert removed.json()["error"]["code"] == "auth.invalid_api_key"
    assert (
        client.get("/v1/auth/check", headers={"X-API-Key": second_key}).status_code
        == 200
    )
