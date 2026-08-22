from collections.abc import Iterator
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from kilasifen.api.app import create_app
from kilasifen.config import get_settings
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.models import ApiKeyModel
from kilasifen.infrastructure.db.session import build_engine, session_scope
from kilasifen.testing.database import managed_test_database_url

_ADMIN_KEY = "bootstrap-admin-secret"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_admin_can_issue_use_and_revoke_consumer_credential(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path, name="access_admin"
    ) as database_url:
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{_ADMIN_KEY}"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
        engine = build_engine(database_url)
        Base.metadata.create_all(engine)

        with TestClient(create_app()) as client:
            created = client.post(
                "/v1/admin/consumers",
                headers={"X-API-Key": _ADMIN_KEY},
                json={"name": "Teko staging"},
            )
            assert created.status_code == 201
            consumer_id = created.json()["data"]["consumer"]["id"]
            duplicate = client.post(
                "/v1/admin/consumers",
                headers={"X-API-Key": _ADMIN_KEY},
                json={"name": "Teko staging"},
            )
            assert duplicate.status_code == 409

            issued = client.post(
                f"/v1/admin/consumers/{consumer_id}/credentials",
                headers={"X-API-Key": _ADMIN_KEY},
                json={
                    "name": "teko-integration",
                    "scopes": ["tenant:read", "tenant:write", "fiscal:write"],
                },
            )
            assert issued.status_code == 201
            credential = issued.json()["data"]["credential"]
            raw_key = credential["api_key"]
            assert raw_key.startswith("ks_")

            emitter = client.post(
                "/v1/emitters",
                headers={"X-API-Key": _ADMIN_KEY},
                json={
                    "owner_consumer_id": consumer_id,
                    "external_id": "teko-staging",
                    "ruc": "80024135",
                    "dv": "5",
                    "legal_name": "TEKO STAGING SA",
                    "tax_environment": "test",
                },
            )
            assert emitter.status_code == 201
            emitter_id = emitter.json()["data"]["emitter"]["id"]

            authenticated = client.get(
                "/v1/auth/check",
                headers={"X-API-Key": raw_key},
            )
            assert authenticated.status_code == 200
            assigned_emitter = client.get(
                f"/v1/emitters/{emitter_id}",
                headers={"X-API-Key": raw_key},
            )
            assert assigned_emitter.status_code == 200

            with session_scope(client.app.state.session_factory) as session:
                stored = session.scalar(
                    select(ApiKeyModel).where(ApiKeyModel.id == credential["id"])
                )
                assert stored is not None
                assert raw_key not in stored.key_hash

            revoked = client.post(
                f"/v1/admin/consumers/{consumer_id}/credentials/{credential['id']}/revoke",
                headers={"X-API-Key": _ADMIN_KEY},
            )
            assert revoked.status_code == 200
            assert revoked.json()["data"]["credential"]["status"] == "revoked"

            rejected = client.get("/v1/auth/check", headers={"X-API-Key": raw_key})
            assert rejected.status_code == 401
