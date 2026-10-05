"""Emitter routes enforce their scope through the shared dependencies."""

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
from kilasifen.testing.typed_documents import (
    FICTIONAL_EMITTER_DV,
    FICTIONAL_EMITTER_NAME,
    FICTIONAL_EMITTER_RUC,
)

ADMIN = {"X-API-Key": "secret-key"}


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    with managed_test_database_url(tmp_path=tmp_path, name="scopes") as database_url:
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", '["secret-key"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
        Base.metadata.create_all(build_engine(database_url))
        with TestClient(create_app()) as test_client:
            yield test_client


@pytest.fixture
def tenant(client: TestClient) -> tuple[str, dict[str, str]]:
    """An emitter and a read-only credential of the consumer that owns it."""

    consumer = client.post(
        "/v1/admin/consumers", headers=ADMIN, json={"name": "ERP ficticio"}
    ).json()["data"]["consumer"]
    emitter = client.post(
        "/v1/emitters",
        headers=ADMIN,
        json={
            "owner_consumer_id": consumer["id"],
            "ruc": FICTIONAL_EMITTER_RUC,
            "dv": FICTIONAL_EMITTER_DV,
            "legal_name": FICTIONAL_EMITTER_NAME,
            "tax_environment": "test",
        },
    ).json()["data"]["emitter"]
    credential = client.post(
        f"/v1/admin/consumers/{consumer['id']}/credentials",
        headers=ADMIN,
        json={"name": "solo lectura", "scopes": ["tenant:read"]},
    ).json()["data"]["credential"]
    return emitter["id"], {"X-API-Key": credential["api_key"]}


def test_read_only_credential_reads_its_emitter(
    client: TestClient, tenant: tuple[str, dict[str, str]]
) -> None:
    emitter_id, headers = tenant

    assert client.get(f"/v1/emitters/{emitter_id}", headers=headers).status_code == 200
    health = client.get(f"/v1/emitters/{emitter_id}/health", headers=headers)
    assert health.status_code == 200


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("patch", "", {"legal_name": "OTRO NOMBRE FICTICIO SA"}),
        # The scope is checked before the body, like in every other router.
        ("patch", "", {"tax_environment": "staging"}),
        ("post", "/deactivate", None),
    ],
    ids=["update", "update-with-invalid-body", "deactivate"],
)
def test_read_only_credential_cannot_change_its_emitter(
    client: TestClient,
    tenant: tuple[str, dict[str, str]],
    method: str,
    suffix: str,
    body: dict | None,
) -> None:
    emitter_id, headers = tenant

    response = client.request(
        method, f"/v1/emitters/{emitter_id}{suffix}", headers=headers, json=body
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.insufficient_scope"
