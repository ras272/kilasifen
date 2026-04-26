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


API_KEY = "secret-key"
CERT_PASSWORD = "test1234"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    with managed_test_database_url(tmp_path=tmp_path, name="certificates") as database_url:
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{API_KEY}"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        monkeypatch.setenv(
            "KILA_SIFEN_ENCRYPTION_KEY",
            Fernet.generate_key().decode(),
        )

        engine = build_engine(database_url)
        Base.metadata.create_all(engine)

        with TestClient(create_app()) as test_client:
            yield test_client


@pytest.fixture
def emitter_id(client: TestClient) -> str:
    response = client.post(
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
    assert response.status_code == 201
    return response.json()["data"]["emitter"]["id"]


def test_upload_list_and_activate_certificate(
    client: TestClient,
    emitter_id: str,
) -> None:
    cert_path = Path(__file__).resolve().parents[1] / "test_cert.pfx"
    with cert_path.open("rb") as certificate_file:
        upload_response = client.post(
            f"/v1/emitters/{emitter_id}/certificates",
            headers={"X-API-Key": API_KEY},
            data={
                "logical_name": "principal",
                "password": CERT_PASSWORD,
            },
            files={"file": ("test_cert.pfx", certificate_file, "application/x-pkcs12")},
        )

    assert upload_response.status_code == 201
    certificate = upload_response.json()["data"]["certificate"]
    assert certificate["logical_name"] == "principal"
    assert certificate["status"] == "uploaded"
    assert certificate["is_active"] is False
    assert certificate["fingerprint"]
    assert "encrypted_p12" not in certificate
    assert "encrypted_password" not in certificate

    certificate_id = certificate["id"]

    list_response = client.get(
        f"/v1/emitters/{emitter_id}/certificates",
        headers={"X-API-Key": API_KEY},
    )

    assert list_response.status_code == 200
    listed = list_response.json()["data"]["certificates"]
    assert len(listed) == 1
    assert listed[0]["id"] == certificate_id
    assert "encrypted_p12" not in listed[0]
    assert "encrypted_password" not in listed[0]

    activate_response = client.post(
        f"/v1/certificates/{certificate_id}/activate",
        headers={"X-API-Key": API_KEY},
    )

    assert activate_response.status_code == 200
    activated = activate_response.json()["data"]["certificate"]
    assert activated["id"] == certificate_id
    assert activated["is_active"] is True
