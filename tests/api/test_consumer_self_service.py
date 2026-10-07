"""An ERP credential onboards its own customers and unblocks their jobs."""

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.config import get_settings
from kilasifen.domain.jobs.models import Job
from kilasifen.engine.sdk.fiscal import calculate_mod11_dv
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.repositories.job_outbox import (
    SqlAlchemyJobOutboxRepository,
)
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.session import build_engine, session_scope
from kilasifen.testing.database import managed_test_database_url
from kilasifen.testing.typed_documents import (
    FICTIONAL_EMITTER_DV,
    FICTIONAL_EMITTER_NAME,
    FICTIONAL_EMITTER_RUC,
)

ADMIN = {"X-API-Key": "secret-key"}
#: Next RUC of the fictional MT v150 series, with its modulo 11 DV.
SECOND_RUC = "44444402"
SECOND_DV = str(calculate_mod11_dv(SECOND_RUC))


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    with managed_test_database_url(tmp_path=tmp_path, name="selfservice") as url:
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", '["secret-key"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", url)
        monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
        Base.metadata.create_all(build_engine(url))
        with TestClient(create_app()) as test_client:
            yield test_client


def _consumer(client: TestClient, name: str) -> str:
    response = client.post("/v1/admin/consumers", headers=ADMIN, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["data"]["consumer"]["id"]


def _credential(client: TestClient, consumer_id: str, *scopes: str) -> dict[str, str]:
    response = client.post(
        f"/v1/admin/consumers/{consumer_id}/credentials",
        headers=ADMIN,
        json={"name": "erp", "scopes": list(scopes)},
    )
    assert response.status_code == 201, response.text
    return {"X-API-Key": response.json()["data"]["credential"]["api_key"]}


def _emitter_payload(
    *, ruc: str = FICTIONAL_EMITTER_RUC, dv: str = FICTIONAL_EMITTER_DV, **extra
) -> dict:
    return {
        "ruc": ruc,
        "dv": dv,
        "legal_name": FICTIONAL_EMITTER_NAME,
        "tax_environment": "test",
        **extra,
    }


def _admin_emitter(client: TestClient, *, owner: str, **payload) -> str:
    response = client.post(
        "/v1/emitters",
        headers=ADMIN,
        json=_emitter_payload(owner_consumer_id=owner, **payload),
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["emitter"]["id"]


def _listed_ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [emitter["id"] for emitter in response.json()["data"]["emitters"]]


def test_erp_credential_creates_emitters_for_its_own_consumer(
    client: TestClient,
) -> None:
    erp = _credential(
        client, _consumer(client, "ERP ficticio"), "emitters:create", "tenant:read"
    )
    outsider = _credential(client, _consumer(client, "Otro ERP"), "tenant:read")

    created = client.post(
        "/v1/emitters", headers=erp, json=_emitter_payload(external_id="erp:cliente-1")
    )

    assert created.status_code == 201, created.text
    emitter_id = created.json()["data"]["emitter"]["id"]
    assert client.get(f"/v1/emitters/{emitter_id}", headers=erp).status_code == 200
    assert client.get(f"/v1/emitters/{emitter_id}", headers=outsider).status_code == 404


def test_erp_credential_may_name_its_own_consumer_as_owner(client: TestClient) -> None:
    consumer_id = _consumer(client, "ERP ficticio")
    erp = _credential(client, consumer_id, "emitters:create", "tenant:read")

    created = client.post(
        "/v1/emitters",
        headers=erp,
        json=_emitter_payload(owner_consumer_id=consumer_id),
    )

    assert created.status_code == 201, created.text
    assert _listed_ids(client.get("/v1/emitters", headers=erp)) == [
        created.json()["data"]["emitter"]["id"]
    ]


def test_erp_credential_cannot_create_emitters_for_another_consumer(
    client: TestClient,
) -> None:
    erp = _credential(
        client, _consumer(client, "ERP ficticio"), "emitters:create", "tenant:read"
    )
    other_consumer = _consumer(client, "Otro ERP")

    response = client.post(
        "/v1/emitters",
        headers=erp,
        json=_emitter_payload(owner_consumer_id=other_consumer),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "emitters.owner_not_allowed"
    assert _listed_ids(client.get("/v1/emitters", headers=ADMIN)) == []


def test_creating_emitters_requires_the_emitters_create_scope(
    client: TestClient,
) -> None:
    every_other_scope = _credential(
        client,
        _consumer(client, "ERP ficticio"),
        "tenant:read",
        "tenant:write",
        "fiscal:write",
        "secrets:write",
    )

    response = client.post(
        "/v1/emitters", headers=every_other_scope, json=_emitter_payload()
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.insufficient_scope"


def test_listing_shows_only_the_emitters_of_the_credential_consumer(
    client: TestClient,
) -> None:
    mine = _consumer(client, "ERP ficticio")
    other = _consumer(client, "Otro ERP")
    own_id = _admin_emitter(client, owner=mine, external_id="erp:cliente-1")
    other_id = _admin_emitter(
        client, owner=other, ruc=SECOND_RUC, dv=SECOND_DV, external_id="otro:cliente-1"
    )
    reader = _credential(client, mine, "tenant:read")

    assert _listed_ids(client.get("/v1/emitters", headers=reader)) == [own_id]
    hidden = client.get(
        "/v1/emitters", headers=reader, params={"external_id": "otro:cliente-1"}
    )
    assert _listed_ids(hidden) == []
    assert sorted(_listed_ids(client.get("/v1/emitters", headers=ADMIN))) == sorted(
        [own_id, other_id]
    )


def test_consumer_without_emitters_lists_none(client: TestClient) -> None:
    _admin_emitter(client, owner=_consumer(client, "Otro ERP"))
    reader = _credential(client, _consumer(client, "ERP nuevo"), "tenant:read")

    assert _listed_ids(client.get("/v1/emitters", headers=reader)) == []


@pytest.mark.parametrize(
    "ruc",
    [FICTIONAL_EMITTER_RUC, f"{FICTIONAL_EMITTER_RUC}-{FICTIONAL_EMITTER_DV}"],
    ids=["without-dv", "with-dv"],
)
def test_listing_filters_by_ruc(client: TestClient, ruc: str) -> None:
    consumer_id = _consumer(client, "ERP ficticio")
    wanted = _admin_emitter(client, owner=consumer_id)
    _admin_emitter(client, owner=consumer_id, ruc=SECOND_RUC, dv=SECOND_DV)
    reader = _credential(client, consumer_id, "tenant:read")

    filtered = client.get("/v1/emitters", headers=reader, params={"ruc": ruc})

    assert _listed_ids(filtered) == [wanted]


def test_lost_creation_response_is_recovered_by_external_id(client: TestClient) -> None:
    erp = _credential(
        client, _consumer(client, "ERP ficticio"), "emitters:create", "tenant:read"
    )
    payload = _emitter_payload(external_id="erp:cliente-1")
    first = client.post("/v1/emitters", headers=erp, json=payload)
    assert first.status_code == 201, first.text

    again = client.post("/v1/emitters", headers=erp, json=payload)

    assert again.status_code == 409
    assert again.json()["error"]["code"] == "emitters.external_id_conflict"
    found = client.get(
        "/v1/emitters", headers=erp, params={"external_id": "erp:cliente-1"}
    )
    assert _listed_ids(found) == [first.json()["data"]["emitter"]["id"]]


def test_listing_requires_tenant_read(client: TestClient) -> None:
    creator = _credential(client, _consumer(client, "ERP ficticio"), "emitters:create")

    response = client.get("/v1/emitters", headers=creator)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.insufficient_scope"


def _seed_job(
    client: TestClient,
    *,
    emitter_id: str,
    status: str,
    job_id: str = "job-ficticio",
) -> str:
    now = datetime.now(timezone.utc)
    finished = status in {"failed", "succeeded"}
    error = {"category": "transport"} if status == "failed" else None
    with session_scope(client.app.state.session_factory) as session:
        SqlAlchemyJobRepository(session).save(
            Job(
                id=job_id,
                emitter_id=emitter_id,
                related_entity_type="document",
                related_entity_id="documento-ficticio",
                job_type="document.emit",
                status=status,
                attempts=1,
                error_snapshot=error,
                scheduled_at=now,
                started_at=now,
                finished_at=now if finished else None,
                worker_correlation_id=None,
                created_at=now,
                updated_at=now,
            )
        )
    return job_id


@pytest.mark.parametrize("status", ["failed", "processing"])
def test_erp_requeues_a_job_of_its_emitter(client: TestClient, status: str) -> None:
    consumer_id = _consumer(client, "ERP ficticio")
    emitter_id = _admin_emitter(client, owner=consumer_id)
    erp = _credential(client, consumer_id, "tenant:read", "fiscal:write")
    job_id = _seed_job(client, emitter_id=emitter_id, status=status)

    response = client.post(
        f"/v1/emitters/{emitter_id}/jobs/{job_id}/retry", headers=erp
    )

    assert response.status_code == 200, response.text
    job = response.json()["data"]["job"]
    assert (job["status"], job["error_snapshot"], job["finished_at"]) == (
        "queued",
        None,
        None,
    )
    with session_scope(client.app.state.session_factory) as session:
        message = SqlAlchemyJobOutboxRepository(session).get_for_job(job_id)
    assert message is not None
    assert message.status == "pending"


def test_job_retry_requires_fiscal_write(client: TestClient) -> None:
    consumer_id = _consumer(client, "ERP ficticio")
    emitter_id = _admin_emitter(client, owner=consumer_id)
    reader = _credential(client, consumer_id, "tenant:read", "tenant:write")
    job_id = _seed_job(client, emitter_id=emitter_id, status="failed")

    response = client.post(
        f"/v1/emitters/{emitter_id}/jobs/{job_id}/retry", headers=reader
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "auth.insufficient_scope"


def test_job_retry_reaches_only_jobs_of_the_consumer_emitters(
    client: TestClient,
) -> None:
    mine = _consumer(client, "ERP ficticio")
    own_emitter = _admin_emitter(client, owner=mine)
    foreign_emitter = _admin_emitter(
        client, owner=_consumer(client, "Otro ERP"), ruc=SECOND_RUC, dv=SECOND_DV
    )
    erp = _credential(client, mine, "fiscal:write")
    foreign_job = _seed_job(client, emitter_id=foreign_emitter, status="failed")

    through_foreign = client.post(
        f"/v1/emitters/{foreign_emitter}/jobs/{foreign_job}/retry", headers=erp
    )
    through_own = client.post(
        f"/v1/emitters/{own_emitter}/jobs/{foreign_job}/retry", headers=erp
    )

    assert through_foreign.status_code == 404
    assert through_foreign.json()["error"]["code"] == "emitters.not_found"
    assert through_own.status_code == 404
    assert through_own.json()["error"]["code"] == "jobs.not_found"
    with session_scope(client.app.state.session_factory) as session:
        untouched = SqlAlchemyJobRepository(session).get(foreign_job)
    assert untouched is not None
    assert untouched.status == "failed"


def test_succeeded_job_is_not_requeued(client: TestClient) -> None:
    consumer_id = _consumer(client, "ERP ficticio")
    emitter_id = _admin_emitter(client, owner=consumer_id)
    erp = _credential(client, consumer_id, "fiscal:write")
    job_id = _seed_job(client, emitter_id=emitter_id, status="succeeded")

    response = client.post(
        f"/v1/emitters/{emitter_id}/jobs/{job_id}/retry", headers=erp
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "jobs.retry_not_allowed"
