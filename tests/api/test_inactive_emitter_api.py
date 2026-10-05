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

_API_KEY = "inactive-emitter-admin"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def inactive_emitter_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[tuple[TestClient, str]]:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="inactive_emitter_api",
    ) as database_url:
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{_API_KEY}"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
        engine = build_engine(database_url)
        Base.metadata.create_all(engine)

        with TestClient(create_app()) as client:
            created = client.post(
                "/v1/emitters",
                headers={"X-API-Key": _API_KEY},
                json={
                    "external_id": "inactive-control",
                    "ruc": "80024135",
                    "dv": "5",
                    "legal_name": "INACTIVE CONTROL SA",
                    "tax_environment": "test",
                },
            )
            assert created.status_code == 201
            emitter_id = created.json()["data"]["emitter"]["id"]
            deactivated = client.post(
                f"/v1/emitters/{emitter_id}/deactivate",
                headers={"X-API-Key": _API_KEY},
            )
            assert deactivated.status_code == 200
            yield client, emitter_id


def test_inactive_emitter_allows_reads_and_non_secret_metadata_update(
    inactive_emitter_client: tuple[TestClient, str],
) -> None:
    client, emitter_id = inactive_emitter_client

    read = client.get(
        f"/v1/emitters/{emitter_id}",
        headers={"X-API-Key": _API_KEY},
    )
    update = client.patch(
        f"/v1/emitters/{emitter_id}",
        headers={"X-API-Key": _API_KEY},
        json={"legal_name": "INACTIVE CONTROL RENAMED SA"},
    )

    assert read.status_code == 200
    assert read.json()["data"]["emitter"]["status"] == "inactive"
    assert update.status_code == 200


@pytest.mark.parametrize(
    ("method", "path_template", "request_kwargs"),
    [
        (
            "post",
            "/v1/emitters/{emitter_id}/documents/facturas",
            {
                "json": {
                    "idempotency_key": "inactive-document",
                    "factura": {
                        "cliente": {
                            "ruc": "80025298-5",
                            "razon_social": "CLIENTE FICTICIO",
                            "tipo_contribuyente": 2,
                        },
                        "items": [
                            {
                                "descripcion": "Servicio",
                                "cantidad": 1,
                                "precioUnitario": 1,
                            }
                        ],
                    },
                }
            },
        ),
        (
            "post",
            "/v1/emitters/{emitter_id}/documents/missing/cancel",
            {"json": {"motivo": "Operacion bloqueada por baja del emisor"}},
        ),
        ("get", "/v1/emitters/{emitter_id}/queries/ruc/80024135", {}),
        (
            "post",
            "/v1/emitters/{emitter_id}/certificates",
            {
                "data": {"logical_name": "principal", "password": "secret"},
                "files": {
                    "file": (
                        "certificate.p12",
                        b"not-decrypted",
                        "application/x-pkcs12",
                    )
                },
            },
        ),
        (
            "post",
            "/v1/emitters/{emitter_id}/stampings",
            {"json": {"number": "12345678", "start_date": "2026-01-01"}},
        ),
        (
            "post",
            "/v1/emitters/{emitter_id}/webhooks",
            {
                "json": {
                    "url": "https://hooks.example.com/kila",
                    "secret": "x" * 32,
                }
            },
        ),
        (
            "patch",
            "/v1/emitters/{emitter_id}",
            {"json": {"csc": "x" * 32, "csc_id": "0001"}},
        ),
    ],
)
def test_inactive_emitter_rejects_new_sensitive_operations(
    inactive_emitter_client: tuple[TestClient, str],
    method: str,
    path_template: str,
    request_kwargs: dict,
) -> None:
    client, emitter_id = inactive_emitter_client

    response = client.request(
        method,
        path_template.format(emitter_id=emitter_id),
        headers={"X-API-Key": _API_KEY},
        **request_kwargs,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "emitters.inactive"
