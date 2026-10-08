"""Consumer keys are checked with SHA-256; PBKDF2 stays off the request path."""

import hashlib
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
from kilasifen.security import (
    fingerprint_api_key,
    hash_api_key,
    is_slow_api_key_hash,
    key_prefix,
    verify_api_key,
)
from kilasifen.testing.database import managed_test_database_url

ADMIN_KEY = "bootstrap-admin-key-for-hashing-tests"
ADMIN = {"X-API-Key": ADMIN_KEY}


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    with managed_test_database_url(tmp_path=tmp_path, name="key_hashing") as url:
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{ADMIN_KEY}"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", url)
        Base.metadata.create_all(build_engine(url))
        with TestClient(create_app()) as test_client:
            yield test_client


@pytest.fixture
def pbkdf2_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Counts every PBKDF2 derivation made through ``hashlib``."""

    calls: list[int] = []
    real = hashlib.pbkdf2_hmac

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(hashlib, "pbkdf2_hmac", counting)
    return calls


def _consumer_key(client: TestClient) -> tuple[str, str]:
    consumer = client.post(
        "/v1/admin/consumers", headers=ADMIN, json={"name": "ERP ficticio"}
    ).json()["data"]["consumer"]["id"]
    credential = client.post(
        f"/v1/admin/consumers/{consumer}/credentials",
        headers=ADMIN,
        json={"name": "erp", "scopes": ["tenant:read"]},
    ).json()["data"]["credential"]
    return credential["id"], credential["api_key"]


def _stored_hash(client: TestClient, credential_id: str) -> str:
    with session_scope(client.app.state.session_factory) as session:
        return session.get(ApiKeyModel, credential_id).key_hash


def test_issued_consumer_keys_are_stored_and_checked_with_sha256(
    client: TestClient, pbkdf2_calls: list[int]
) -> None:
    credential_id, raw_key = _consumer_key(client)
    pbkdf2_calls.clear()

    for _ in range(3):
        response = client.get("/v1/auth/check", headers={"X-API-Key": raw_key})
        assert response.status_code == 200

    stored = _stored_hash(client, credential_id)
    assert stored == fingerprint_api_key(raw_key)
    assert not is_slow_api_key_hash(stored)
    assert pbkdf2_calls == []


def test_a_key_stored_with_pbkdf2_moves_to_sha256_on_first_use(
    client: TestClient, pbkdf2_calls: list[int]
) -> None:
    credential_id, raw_key = _consumer_key(client)
    with session_scope(client.app.state.session_factory) as session:
        session.get(ApiKeyModel, credential_id).key_hash = hash_api_key(raw_key)
    pbkdf2_calls.clear()

    first = client.get("/v1/auth/check", headers={"X-API-Key": raw_key})
    second = client.get("/v1/auth/check", headers={"X-API-Key": raw_key})

    assert (first.status_code, second.status_code) == (200, 200)
    assert _stored_hash(client, credential_id) == fingerprint_api_key(raw_key)
    assert len(pbkdf2_calls) == 1


@pytest.mark.parametrize("stored_as", ["sha256", "pbkdf2"])
def test_a_wrong_key_with_the_same_prefix_is_rejected(
    client: TestClient, stored_as: str
) -> None:
    credential_id, raw_key = _consumer_key(client)
    if stored_as == "pbkdf2":
        with session_scope(client.app.state.session_factory) as session:
            session.get(ApiKeyModel, credential_id).key_hash = hash_api_key(raw_key)
    forged = raw_key[:-1] + ("A" if raw_key[-1] != "A" else "B")
    assert key_prefix(forged) == key_prefix(raw_key)

    response = client.get("/v1/auth/check", headers={"X-API-Key": forged})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.invalid_api_key"


def test_the_bootstrap_key_keeps_pbkdf2_but_derives_it_once_per_process(
    client: TestClient, pbkdf2_calls: list[int]
) -> None:
    for _ in range(4):
        assert client.get("/v1/auth/check", headers=ADMIN).status_code == 200
    derivations = len(pbkdf2_calls)

    with session_scope(client.app.state.session_factory) as session:
        stored = session.scalar(
            select(ApiKeyModel.key_hash).where(ApiKeyModel.name == "bootstrap-0")
        )
    # The row did not exist: one derivation stored it; the rest skipped PBKDF2.
    assert derivations == 1
    assert is_slow_api_key_hash(stored)
    assert verify_api_key(ADMIN_KEY, stored)


def test_a_bootstrap_row_lost_under_the_process_is_stored_again(
    client: TestClient,
) -> None:
    assert client.get("/v1/auth/check", headers=ADMIN).status_code == 200
    with session_scope(client.app.state.session_factory) as session:
        row = session.scalar(
            select(ApiKeyModel).where(ApiKeyModel.name == "bootstrap-0")
        )
        session.delete(row)

    assert client.get("/v1/auth/check", headers=ADMIN).status_code == 200


@pytest.mark.parametrize(
    "encoded", ["sha256$", "sha256$not-base64!!", "sha256", "md5$abc", ""]
)
def test_malformed_hashes_never_verify(encoded: str) -> None:
    assert verify_api_key("ks_cualquier-clave", encoded) is False
