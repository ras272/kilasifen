from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.api.deps import get_admin_service
from kilasifen.application.admin.service import AdminConsoleService
from kilasifen.application.certificates.service import CertificateService
from kilasifen.application.webhooks.service import WebhookService
from kilasifen.config import get_settings
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.repositories.certificates import SqlAlchemyCertificateRepository
from kilasifen.infrastructure.db.repositories.documents import SqlAlchemyDocumentRepository
from kilasifen.infrastructure.db.repositories.emitters import SqlAlchemyEmitterRepository
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.repositories.stampings import SqlAlchemyStampingRepository
from kilasifen.infrastructure.db.repositories.webhooks import SqlAlchemyWebhookRepository
from kilasifen.infrastructure.db.session import build_engine, build_session_factory, session_scope
from kilasifen.infrastructure.webhooks.deliverer import WebhookDeliverer
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
    with managed_test_database_url(tmp_path=tmp_path, name="admin") as database_url:
        encryption_key = Fernet.generate_key().decode()
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{API_KEY}"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", encryption_key)

        engine = build_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = build_session_factory(engine)
        fake_queue = _FakeAdminQueue()

        app = create_app()

        def _get_fake_admin_service():
            with session_scope(session_factory) as session:
                settings = get_settings()
                certificate_repository = SqlAlchemyCertificateRepository(session)
                emitter_repository = SqlAlchemyEmitterRepository(session)
                certificate_service = CertificateService(
                    certificate_repository=certificate_repository,
                    emitter_repository=emitter_repository,
                    certificate_store=EncryptedCertificateStore(settings.encryption_key),
                )
                yield AdminConsoleService(
                    emitter_repository=emitter_repository,
                    certificate_repository=certificate_repository,
                    stamping_repository=SqlAlchemyStampingRepository(session),
                    document_repository=SqlAlchemyDocumentRepository(session),
                    job_repository=SqlAlchemyJobRepository(session),
                    webhook_repository=SqlAlchemyWebhookRepository(session),
                    certificate_service=certificate_service,
                    document_queue=fake_queue,
                    webhook_queue=fake_queue,
                    database_url=settings.database_url,
                    encryption_key=settings.encryption_key,
                )

        app.dependency_overrides[get_admin_service] = _get_fake_admin_service
        with TestClient(app) as test_client:
            test_client.app.state.session_factory = session_factory
            test_client.app.state.fake_admin_queue = fake_queue
            yield test_client


@pytest.fixture
def seeded_ids(client: TestClient) -> dict[str, str]:
    headers = {"X-API-Key": API_KEY}
    emitter_response = client.post(
        "/v1/emitters",
        headers=headers,
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
    emitter_id = emitter_response.json()["data"]["emitter"]["id"]

    cert_path = Path(__file__).resolve().parents[1] / "test_cert.pfx"
    with cert_path.open("rb") as cert_one:
        upload_main = client.post(
            f"/v1/emitters/{emitter_id}/certificates",
            headers=headers,
            data={"logical_name": "main", "password": CERT_PASSWORD},
            files={"file": ("main.pfx", cert_one, "application/x-pkcs12")},
        )
    certificate_id = upload_main.json()["data"]["certificate"]["id"]

    with cert_path.open("rb") as cert_backup:
        upload_backup = client.post(
            f"/v1/emitters/{emitter_id}/certificates",
            headers=headers,
            data={"logical_name": "backup", "password": CERT_PASSWORD},
            files={"file": ("backup.pfx", cert_backup, "application/x-pkcs12")},
        )
    backup_certificate_id = upload_backup.json()["data"]["certificate"]["id"]

    client.post(f"/v1/emitters/{emitter_id}/certificates/{certificate_id}/activate", headers=headers)

    stamping_response = client.post(
        f"/v1/emitters/{emitter_id}/stampings",
        headers=headers,
        json={
            "number": "80024135",
            "start_date": "2024-03-11",
            "end_date": None,
        },
    )
    stamping_id = stamping_response.json()["data"]["stamping"]["id"]
    client.post(f"/v1/emitters/{emitter_id}/stampings/{stamping_id}/activate", headers=headers)

    document_response = client.post(
        f"/v1/emitters/{emitter_id}/documents",
        headers=headers,
        json={
            "external_id": "erp-admin-1",
            "idempotency_key": "idem-admin-1",
            "document_type": "factura",
            "payload": {"total": "100000"},
        },
    )
    document_job_id = document_response.json()["data"]["job"]["id"]

    webhook_delivery_id, webhook_job_id = _seed_webhook_failure(
        client=client,
        emitter_id=emitter_id,
    )

    with session_scope(client.app.state.session_factory) as session:
        jobs = SqlAlchemyJobRepository(session)
        document_job = jobs.get(document_job_id)
        webhook_job = jobs.get(webhook_job_id)
        assert document_job is not None
        assert webhook_job is not None
        jobs.save(
            replace(
                document_job,
                status="failed",
                error_snapshot={"category": "transport", "message": "timeout"},
                updated_at=_now(),
            )
        )
        jobs.save(
            replace(
                webhook_job,
                status="failed",
                error_snapshot={"category": "delivery_failed", "message": "500"},
                updated_at=_now(),
            )
        )

    return {
        "emitter_id": emitter_id,
        "certificate_id": certificate_id,
        "backup_certificate_id": backup_certificate_id,
        "document_job_id": document_job_id,
        "webhook_delivery_id": webhook_delivery_id,
        "webhook_job_id": webhook_job_id,
    }


def test_admin_pages_render_with_operational_data(
    client: TestClient,
    seeded_ids: dict[str, str],
) -> None:
    headers = {"X-API-Key": API_KEY}
    emitter_id = seeded_ids["emitter_id"]

    emitters_page = client.get("/admin/emitters", headers=headers)
    documents_page = client.get("/admin/documents", headers=headers)
    jobs_page = client.get("/admin/jobs", headers=headers)
    webhooks_page = client.get("/admin/webhooks", headers=headers)
    detail_page = client.get(f"/admin/emitters/{emitter_id}", headers=headers)

    assert emitters_page.status_code == 200
    assert "ARES PARAGUAY SRL" in emitters_page.text
    assert documents_page.status_code == 200
    assert "erp-admin-1" in documents_page.text
    assert jobs_page.status_code == 200
    assert seeded_ids["document_job_id"] in jobs_page.text
    assert webhooks_page.status_code == 200
    assert seeded_ids["webhook_delivery_id"] in webhooks_page.text
    assert detail_page.status_code == 200
    assert "Certificates" in detail_page.text
    assert "Stampings" in detail_page.text
    assert "Failed webhook deliveries" in detail_page.text


def test_admin_activate_certificate_switches_active(
    client: TestClient,
    seeded_ids: dict[str, str],
) -> None:
    headers = {"X-API-Key": API_KEY}
    backup_certificate_id = seeded_ids["backup_certificate_id"]
    emitter_id = seeded_ids["emitter_id"]

    response = client.post(
        f"/admin/certificates/{backup_certificate_id}/activate",
        headers=headers,
        data={"next_url": f"/admin/emitters/{emitter_id}"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/admin/emitters/{emitter_id}"

    certificates_response = client.get(
        f"/v1/emitters/{emitter_id}/certificates",
        headers=headers,
    )
    assert certificates_response.status_code == 200
    certificates = certificates_response.json()["data"]["certificates"]
    active_ids = [item["id"] for item in certificates if item["is_active"]]
    assert active_ids == [backup_certificate_id]


def test_admin_retry_job_requeues_document_job(
    client: TestClient,
    seeded_ids: dict[str, str],
) -> None:
    headers = {"X-API-Key": API_KEY}
    document_job_id = seeded_ids["document_job_id"]

    response = client.post(
        f"/admin/jobs/{document_job_id}/retry",
        headers=headers,
        data={"next_url": "/admin/jobs"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/jobs"

    job_response = client.get(
        f"/v1/emitters/{seeded_ids['emitter_id']}/jobs/{document_job_id}",
        headers=headers,
    )
    assert job_response.status_code == 200
    assert job_response.json()["data"]["job"]["status"] == "queued"

    assert document_job_id in client.app.state.fake_admin_queue.document_job_ids


def _seed_webhook_failure(client: TestClient, emitter_id: str) -> tuple[str, str]:
    settings = get_settings()
    with session_scope(client.app.state.session_factory) as session:
        service = WebhookService(
            webhook_repository=SqlAlchemyWebhookRepository(session),
            emitter_repository=SqlAlchemyEmitterRepository(session),
            job_repository=SqlAlchemyJobRepository(session),
            secret_store=EncryptedCertificateStore(settings.encryption_key),
            queue=_NoopWebhookQueue(),
            deliverer=WebhookDeliverer(sender=lambda *_args, **_kwargs: None),
        )
        endpoint = service.register_endpoint(
            emitter_id=emitter_id,
            url="https://erp.example.com/hooks/kila",
            secret="top-secret",
            event_subscriptions=["document.approved"],
            retry_policy={"max_attempts": 3},
        )
        delivery, job = service.replay_delivery_for_emitter(
            emitter_id=emitter_id,
            endpoint_id=endpoint.id,
            event_type="document.approved",
            payload={"document_id": "doc-admin-1"},
        )
        deliveries = SqlAlchemyWebhookRepository(session)
        deliveries.save_delivery(
            replace(
                delivery,
                final_status="failed",
                response_code=500,
                response_body_snapshot="upstream_error",
                updated_at=_now(),
            )
        )
        return delivery.id, job.id


class _FakeAdminQueue:
    def __init__(self) -> None:
        self.document_job_ids: list[str] = []
        self.webhook_job_ids: list[str] = []

    def enqueue_document_emit(self, job, *, database_url: str, encryption_key: str):
        assert database_url
        assert encryption_key
        self.document_job_ids.append(job.id)
        return {"job_id": job.id}

    def enqueue_webhook_delivery(self, job, *, database_url: str, encryption_key: str):
        assert database_url
        assert encryption_key
        self.webhook_job_ids.append(job.id)
        return {"job_id": job.id}


class _NoopWebhookQueue:
    def enqueue_webhook_delivery(self, *args, **kwargs):
        del args, kwargs
        return None


def _now() -> datetime:
    return datetime.now(UTC)

