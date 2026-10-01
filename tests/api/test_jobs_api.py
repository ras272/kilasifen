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
from tests._raw_xml import raw_document_payload

API_KEY = "secret-key"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    with managed_test_database_url(tmp_path=tmp_path, name="jobs") as database_url:
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
    emitter_response = client.post(
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
    return emitter_response.json()["data"]["emitter"]["id"]


@pytest.fixture
def second_emitter_id(client: TestClient) -> str:
    emitter_response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-otro",
            "ruc": "80111111",
            "dv": "9",
            "legal_name": "OTRO EMISOR SA",
            "tax_environment": "test",
            "csc": None,
            "csc_id": None,
        },
    )
    return emitter_response.json()["data"]["emitter"]["id"]


@pytest.fixture
def created_job_id(client: TestClient, emitter_id: str) -> str:
    document_response = client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-doc-1",
            "idempotency_key": "idem-1",
            "document_type": "factura",
            "payload": {"total": "100000"},
        },
    )
    return document_response.json()["data"]["job"]["id"]


def test_get_job_returns_detail(
    client: TestClient,
    emitter_id: str,
    created_job_id: str,
) -> None:
    response = client.get(
        f"/v1/emitters/{emitter_id}/jobs/{created_job_id}",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    job = response.json()["data"]["job"]
    assert job["id"] == created_job_id
    assert job["job_type"] == "document.emit"
    assert job["status"] == "queued"


def test_get_job_returns_not_found_for_other_emitter(
    client: TestClient,
    emitter_id: str,
    second_emitter_id: str,
) -> None:
    created = client.post(
        f"/v1/emitters/{second_emitter_id}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-doc-foreign",
            "idempotency_key": "idem-foreign",
            "document_type": "factura",
            "payload": raw_document_payload(),
        },
    )
    foreign_job_id = created.json()["data"]["job"]["id"]

    response = client.get(
        f"/v1/emitters/{emitter_id}/jobs/{foreign_job_id}",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "jobs.not_found"


def test_get_job_requires_valid_api_key(
    client: TestClient,
    emitter_id: str,
    created_job_id: str,
) -> None:
    response = client.get(
        f"/v1/emitters/{emitter_id}/jobs/{created_job_id}",
        headers={"X-API-Key": "wrong-key"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.invalid_api_key"


def test_list_jobs_returns_recent_jobs(client: TestClient, created_job_id: str) -> None:
    response = client.get(
        "/v1/jobs?limit=20&offset=0",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["pagination"]["limit"] == 20
    assert body["pagination"]["offset"] == 0
    assert body["pagination"]["count"] >= 1
    assert any(job["id"] == created_job_id for job in body["jobs"])


def test_list_jobs_can_filter_by_emitter(client: TestClient) -> None:
    emitter_a = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-a",
            "ruc": "80024135",
            "dv": "5",
            "legal_name": "ARES PARAGUAY SRL",
            "tax_environment": "test",
            "csc": None,
            "csc_id": None,
        },
    ).json()["data"]["emitter"]["id"]
    emitter_b = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-b",
            "ruc": "80111111",
            "dv": "9",
            "legal_name": "OTRO EMISOR SA",
            "tax_environment": "test",
            "csc": None,
            "csc_id": None,
        },
    ).json()["data"]["emitter"]["id"]

    client.post(
        f"/v1/emitters/{emitter_a}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "doc-a",
            "idempotency_key": "idem-a",
            "document_type": "factura",
            "payload": raw_document_payload(),
        },
    )
    client.post(
        f"/v1/emitters/{emitter_b}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "doc-b",
            "idempotency_key": "idem-b",
            "document_type": "factura",
            "payload": raw_document_payload(),
        },
    )

    response = client.get(
        f"/v1/jobs?emitter_id={emitter_a}",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    jobs = response.json()["data"]["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["emitter_id"] == emitter_a


def test_list_jobs_without_emitter_filter_returns_system_wide_jobs(
    client: TestClient,
) -> None:
    emitter_a = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-a-global",
            "ruc": "80024135",
            "dv": "5",
            "legal_name": "ARES PARAGUAY SRL",
            "tax_environment": "test",
            "csc": None,
            "csc_id": None,
        },
    ).json()["data"]["emitter"]["id"]
    emitter_b = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-b-global",
            "ruc": "80111111",
            "dv": "9",
            "legal_name": "OTRO EMISOR SA",
            "tax_environment": "test",
            "csc": None,
            "csc_id": None,
        },
    ).json()["data"]["emitter"]["id"]

    client.post(
        f"/v1/emitters/{emitter_a}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "doc-a-global",
            "idempotency_key": "idem-a-global",
            "document_type": "factura",
            "payload": raw_document_payload(),
        },
    )
    client.post(
        f"/v1/emitters/{emitter_b}/documents",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "doc-b-global",
            "idempotency_key": "idem-b-global",
            "document_type": "factura",
            "payload": raw_document_payload(),
        },
    )

    response = client.get("/v1/jobs?limit=20&offset=0", headers={"X-API-Key": API_KEY})

    assert response.status_code == 200
    jobs = response.json()["data"]["jobs"]
    emitters = {job["emitter_id"] for job in jobs}
    assert emitter_a in emitters
    assert emitter_b in emitters


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=101", "offset=-1"],
)
def test_list_jobs_rejects_unbounded_pagination(
    client: TestClient,
    query: str,
) -> None:
    response = client.get(
        f"/v1/jobs?{query}",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 422
