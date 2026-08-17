from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.config import get_settings
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.models import (
    ApiKeyModel,
    ConsumerEmitterModel,
    ConsumerModel,
    EmitterModel,
)
from kilasifen.infrastructure.db.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from kilasifen.security import (
    FISCAL_WRITE_SCOPE,
    TENANT_READ_SCOPE,
    TENANT_WRITE_SCOPE,
    hash_api_key,
    key_prefix,
)
from kilasifen.testing.database import managed_test_database_url

_KEY_A = "ks_test_consumer_a_000000000000000001"
_KEY_B = "ks_test_consumer_b_000000000000000002"
_READ_ONLY_KEY = "ks_test_consumer_a_read_only_000000003"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    with managed_test_database_url(
        tmp_path=tmp_path, name="tenant_isolation"
    ) as database_url:
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", "[]")
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
        engine = build_engine(database_url)
        Base.metadata.create_all(engine)
        _seed_tenants(build_session_factory(engine))
        with TestClient(create_app()) as test_client:
            yield test_client


def test_credentials_can_use_only_owned_emitters(client: TestClient) -> None:
    own = client.get(
        "/v1/emitters/emitter-a",
        headers={"X-API-Key": _KEY_A},
    )
    foreign = client.get(
        "/v1/emitters/emitter-b",
        headers={"X-API-Key": _KEY_A},
    )
    peer = client.get(
        "/v1/emitters/emitter-b",
        headers={"X-API-Key": _KEY_B},
    )

    assert own.status_code == 200
    assert peer.status_code == 200
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "emitters.not_found"


def test_scopes_and_admin_boundary_are_enforced(client: TestClient) -> None:
    raw_create_response = client.post(
        "/v1/emitters/emitter-a/documents",
        headers={"X-API-Key": _KEY_A},
        json={
            "external_id": "tenant-a-document",
            "idempotency_key": "tenant-a-idempotency",
            "document_type": "factura",
            "payload": {"generated_xml": "<rDE><DE Id='A1'/></rDE>", "doc_id": "A1"},
        },
    )
    create_response = client.post(
        "/v1/emitters/emitter-a/documents/facturas",
        headers={"X-API-Key": _KEY_A},
        json={
            "external_id": "tenant-a-document",
            "idempotency_key": "tenant-a-idempotency",
            "factura": {
                "cliente": {
                    "ruc": "80000001-1",
                    "razon_social": "CLIENTE TENANT A",
                },
                "items": [
                    {"descripcion": "Servicio", "cantidad": 1, "precioUnitario": 1}
                ],
            },
        },
    )
    read_only_response = client.post(
        "/v1/emitters/emitter-a/documents",
        headers={"X-API-Key": _READ_ONLY_KEY},
        json={
            "external_id": "forbidden-document",
            "idempotency_key": "forbidden-idempotency",
            "document_type": "factura",
            "payload": {},
        },
    )
    global_jobs_response = client.get(
        "/v1/jobs",
        headers={"X-API-Key": _KEY_A},
    )
    raw_event_response = client.post(
        "/v1/emitters/emitter-a/events",
        headers={"X-API-Key": _KEY_A},
        json={"document_id": "unknown", "event_type": "raw", "payload": {}},
    )
    secret_update_response = client.patch(
        "/v1/emitters/emitter-a",
        headers={"X-API-Key": _KEY_A},
        json={"csc": "caller-must-not-write-this", "csc_id": "0001"},
    )
    read_only_stamping_response = client.post(
        "/v1/emitters/emitter-a/stampings",
        headers={"X-API-Key": _READ_ONLY_KEY},
        json={"number": "12345678", "start_date": "2026-01-01"},
    )

    assert raw_create_response.status_code == 403
    assert create_response.status_code == 201
    assert read_only_response.status_code == 403
    assert read_only_response.json()["error"]["code"] == "auth.insufficient_scope"
    assert global_jobs_response.status_code == 403
    assert raw_event_response.status_code == 403
    assert secret_update_response.status_code == 403
    assert read_only_stamping_response.status_code == 403


def _seed_tenants(session_factory) -> None:
    with session_scope(session_factory) as session:
        session.add_all(
            [
                ConsumerModel(id="consumer-a", name="Consumer A", status="active"),
                ConsumerModel(id="consumer-b", name="Consumer B", status="active"),
                EmitterModel(
                    id="emitter-a",
                    external_id="erp-a",
                    ruc="80000001",
                    dv="1",
                    legal_name="Emitter A",
                    tax_environment="test",
                    status="active",
                ),
                EmitterModel(
                    id="emitter-b",
                    external_id="erp-b",
                    ruc="80000002",
                    dv="2",
                    legal_name="Emitter B",
                    tax_environment="test",
                    status="active",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                ConsumerEmitterModel(consumer_id="consumer-a", emitter_id="emitter-a"),
                ConsumerEmitterModel(consumer_id="consumer-b", emitter_id="emitter-b"),
                _credential(
                    "credential-a",
                    "consumer-a",
                    _KEY_A,
                    [TENANT_READ_SCOPE, TENANT_WRITE_SCOPE, FISCAL_WRITE_SCOPE],
                ),
                _credential(
                    "credential-b",
                    "consumer-b",
                    _KEY_B,
                    [TENANT_READ_SCOPE, TENANT_WRITE_SCOPE, FISCAL_WRITE_SCOPE],
                ),
                _credential(
                    "credential-read-only",
                    "consumer-a",
                    _READ_ONLY_KEY,
                    [TENANT_READ_SCOPE],
                ),
            ]
        )


def _credential(
    credential_id: str,
    consumer_id: str,
    raw_key: str,
    scopes: list[str],
) -> ApiKeyModel:
    return ApiKeyModel(
        id=credential_id,
        consumer_id=consumer_id,
        name=credential_id,
        key_prefix=key_prefix(raw_key),
        key_hash=hash_api_key(raw_key),
        scopes=scopes,
        status="active",
    )
