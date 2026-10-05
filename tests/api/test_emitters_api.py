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
from kilasifen.testing.fiscal_profiles import fictional_fiscal_profile_payload
from tests._raw_xml import raw_document_payload

API_KEY = "secret-key"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    with managed_test_database_url(tmp_path=tmp_path, name="emitters") as database_url:
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{API_KEY}"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())

        engine = build_engine(database_url)
        Base.metadata.create_all(engine)

        with TestClient(create_app()) as test_client:
            yield test_client


def test_create_get_update_and_deactivate_emitter(client: TestClient) -> None:
    create_response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-ares",
            "ruc": "80024135",
            "dv": "5",
            "legal_name": "ARES PARAGUAY SRL",
            "tax_environment": "test",
            "csc": "ABCD0000000000000000000000000000",
            "csc_id": "0001",
        },
    )

    assert create_response.status_code == 201
    created_emitter = create_response.json()["data"]["emitter"]
    assert created_emitter["external_id"] == "erp-ares"
    assert created_emitter["status"] == "active"

    emitter_id = created_emitter["id"]

    get_response = client.get(
        f"/v1/emitters/{emitter_id}",
        headers={"X-API-Key": API_KEY},
    )

    assert get_response.status_code == 200
    fetched_emitter = get_response.json()["data"]["emitter"]
    assert fetched_emitter["ruc"] == "80024135"
    assert fetched_emitter["dv"] == "5"

    update_response = client.patch(
        f"/v1/emitters/{emitter_id}",
        headers={"X-API-Key": API_KEY},
        json={
            "legal_name": "ARES PARAGUAY SRL ACTUALIZADA",
            "csc_id": "0002",
        },
    )

    assert update_response.status_code == 200
    updated_emitter = update_response.json()["data"]["emitter"]
    assert updated_emitter["legal_name"] == "ARES PARAGUAY SRL ACTUALIZADA"
    assert updated_emitter["csc_id"] == "0002"

    deactivate_response = client.post(
        f"/v1/emitters/{emitter_id}/deactivate",
        headers={"X-API-Key": API_KEY},
    )

    assert deactivate_response.status_code == 200
    deactivated_emitter = deactivate_response.json()["data"]["emitter"]
    assert deactivated_emitter["status"] == "inactive"


def test_create_emitter_rejects_duplicate_external_id(client: TestClient) -> None:
    payload = {
        "external_id": "erp-ares",
        "ruc": "80024135",
        "dv": "5",
        "legal_name": "ARES PARAGUAY SRL",
        "tax_environment": "test",
        "csc": None,
        "csc_id": None,
    }

    first_response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json=payload,
    )
    assert first_response.status_code == 201

    second_response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            **payload,
            "ruc": "80111111",
            "dv": "0",
        },
    )

    assert second_response.status_code == 409
    assert second_response.json()["error"]["code"] == "emitters.external_id_conflict"


def test_get_emitter_health_returns_operational_snapshot(client: TestClient) -> None:
    create_response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-health",
            "ruc": "81234123",
            "dv": "6",
            "legal_name": "EMITTER HEALTH SA",
            "tax_environment": "test",
            "csc": None,
            "csc_id": None,
        },
    )
    emitter_id = create_response.json()["data"]["emitter"]["id"]
    client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-health-doc-1",
            "idempotency_key": "idem-health-doc-1",
            "document_type": "factura",
            "payload": raw_document_payload(),
        },
    )

    response = client.get(
        f"/v1/emitters/{emitter_id}/health",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    health = response.json()["data"]["health"]
    assert health["emitter_id"] == emitter_id
    assert health["emitter_status"] == "active"
    assert health["has_active_certificate"] is False
    assert health["has_active_stamping"] is False
    assert health["last_document_id"] is not None


def test_create_emitter_rejects_a_dv_that_is_not_the_modulo_11(
    client: TestClient,
) -> None:
    # MT v150 p. 211: "RUC Emisor: 44444401-7" (validation 1253, D102).
    response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "ruc": "44444401",
            "dv": "8",
            "legal_name": "EMISOR FICTICIO SA",
            "tax_environment": "test",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "emitters.dv_mismatch"


def test_create_emitter_accepts_short_ruc_and_normalizes_csc_id(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "ruc": "123",
            "dv": "6",
            "legal_name": "PERSONA FISICA FICTICIA",
            "tax_environment": "test",
            "csc": "ABCD0000000000000000000000000000",
            "csc_id": "1",
        },
    )

    assert response.status_code == 201
    emitter = response.json()["data"]["emitter"]
    assert emitter["ruc"] == "123"
    assert emitter["csc_id"] == "0001"


@pytest.mark.parametrize(
    "override",
    [
        {"ruc": "0123456"},
        {"ruc": "123456789"},
        {"legal_name": "ABC"},
        {"csc": "short-csc"},
        {"csc_id": "12345"},
    ],
)
def test_create_emitter_rejects_identity_outside_official_formats(
    client: TestClient, override: dict
) -> None:
    payload = {
        "ruc": "44444401",
        "dv": "7",
        "legal_name": "EMISOR FICTICIO SA",
        "tax_environment": "test",
        **override,
    }

    response = client.post("/v1/emitters", headers={"X-API-Key": API_KEY}, json=payload)

    assert response.status_code == 422


def test_update_emitter_rejects_csc_id_zero(client: TestClient) -> None:
    created = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "ruc": "44444401",
            "dv": "7",
            "legal_name": "EMISOR FICTICIO SA",
            "tax_environment": "test",
        },
    )
    emitter_id = created.json()["data"]["emitter"]["id"]

    response = client.patch(
        f"/v1/emitters/{emitter_id}",
        headers={"X-API-Key": API_KEY},
        json={"csc_id": "0000"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "emitters.csc_id_invalid"


def test_emitter_without_fiscal_profile_reports_it_incomplete(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "ruc": "44444401",
            "dv": "7",
            "legal_name": "EMISOR FICTICIO SA",
            "tax_environment": "test",
        },
    )

    emitter = response.json()["data"]["emitter"]
    assert emitter["fiscal_profile"] is None
    assert emitter["fiscal_profile_complete"] is False


def test_fiscal_profile_is_persisted_and_replaced_whole(client: TestClient) -> None:
    profile = fictional_fiscal_profile_payload()
    profile["domicilio"]["descripcion_departamento"] = None
    created = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "ruc": "44444401",
            "dv": "7",
            "legal_name": "EMISOR FICTICIO SA",
            "tax_environment": "test",
            "fiscal_profile": profile,
        },
    )
    assert created.status_code == 201
    emitter = created.json()["data"]["emitter"]
    assert emitter["fiscal_profile_complete"] is True
    stored = emitter["fiscal_profile"]
    assert stored["domicilio"]["descripcion_departamento"] == "CAPITAL"
    assert stored["actividades_economicas"] == profile["actividades_economicas"]

    replacement = fictional_fiscal_profile_payload()
    replacement["tipo_contribuyente"] = 1
    replacement["establecimientos"] = [
        {
            **replacement["domicilio"],
            "establecimiento": "002",
            "direccion": "SUCURSAL FICTICIA",
            "departamento": 12,
            "descripcion_departamento": "CENTRAL",
            "ciudad": 5,
            "descripcion_ciudad": "CIUDAD FICTICIA",
        }
    ]
    updated = client.patch(
        f"/v1/emitters/{emitter['id']}",
        headers={"X-API-Key": API_KEY},
        json={"fiscal_profile": replacement},
    )
    assert updated.status_code == 200

    fetched = client.get(
        f"/v1/emitters/{emitter['id']}", headers={"X-API-Key": API_KEY}
    ).json()["data"]["emitter"]
    assert fetched["legal_name"] == "EMISOR FICTICIO SA"
    assert fetched["fiscal_profile"]["tipo_contribuyente"] == 1
    branch = fetched["fiscal_profile"]["establecimientos"][0]
    assert branch["establecimiento"] == "002"
    assert branch["descripcion_departamento"] == "CENTRAL"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("domicilio", "departamento"), 21),
        (("domicilio", "descripcion_departamento"), "CENTRAL"),
        (("domicilio", "email"), "no-es-un-email"),
        (("domicilio", "telefono"), "12345"),
        (("domicilio", "numero_casa"), "S/N"),
        (("actividades_economicas",), []),
        (("tipo_contribuyente",), 3),
    ],
)
def test_fiscal_profile_outside_official_formats_is_rejected(
    client: TestClient, path: tuple, value
) -> None:
    profile = fictional_fiscal_profile_payload()
    target = profile
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "ruc": "44444401",
            "dv": "7",
            "legal_name": "EMISOR FICTICIO SA",
            "tax_environment": "test",
            "fiscal_profile": profile,
        },
    )

    assert response.status_code == 422
