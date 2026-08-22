from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.api.deps import get_webhook_service
from kilasifen.application.webhooks.service import WebhookService
from kilasifen.config import get_settings
from kilasifen.domain.emitters.models import Emitter
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.repositories.emitters import (
    SqlAlchemyEmitterRepository,
)
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.repositories.webhooks import (
    SqlAlchemyWebhookRepository,
)
from kilasifen.infrastructure.db.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from kilasifen.infrastructure.jobs.queue import WebhookJobQueue
from kilasifen.infrastructure.webhooks.deliverer import WebhookDeliverer
from kilasifen.infrastructure.webhooks.security import WebhookUrlPolicy
from kilasifen.testing.database import managed_test_database_url

API_KEY = "secret-key"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    with managed_test_database_url(tmp_path=tmp_path, name="webhooks") as database_url:
        encryption_key = Fernet.generate_key().decode()
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{API_KEY}"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", encryption_key)

        engine = build_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = build_session_factory(engine)
        _seed_emitter(session_factory, encryption_key)

        app = create_app()

        class FakeWebhookQueue(WebhookJobQueue):
            def __init__(self):
                self.enqueued_job_ids: list[str] = []

            def enqueue_webhook_delivery(
                self, job, *, database_url: str, encryption_key: str
            ):
                self.enqueued_job_ids.append(job.id)
                return {"job_id": job.id}

        fake_queue = FakeWebhookQueue()

        def _get_fake_webhook_service():
            with session_scope(session_factory) as session:
                yield WebhookService(
                    webhook_repository=SqlAlchemyWebhookRepository(session),
                    emitter_repository=SqlAlchemyEmitterRepository(
                        session,
                        EncryptedCertificateStore(encryption_key),
                    ),
                    job_repository=SqlAlchemyJobRepository(session),
                    secret_store=EncryptedCertificateStore(encryption_key),
                    queue=fake_queue,
                    deliverer=WebhookDeliverer(
                        sender=lambda *_args, **_kwargs: None,
                        url_policy=WebhookUrlPolicy(
                            resolver=lambda _host, _port: ["93.184.216.34"]
                        ),
                    ),
                )

        app.dependency_overrides[get_webhook_service] = _get_fake_webhook_service
        with TestClient(app) as test_client:
            yield test_client


def test_register_webhook_endpoint_returns_redacted_data(client: TestClient) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/webhooks",
        headers={"X-API-Key": API_KEY},
        json={
            "url": "https://erp.example.com/hooks/kila",
            "secret": "top-secret-webhook-key-000000000000",
            "event_subscriptions": ["document.approved", "event.approved"],
            "retry_policy": {"max_attempts": 3},
        },
    )

    assert response.status_code == 201
    endpoint = response.json()["data"]["webhook_endpoint"]
    assert endpoint["emitter_id"] == "emitter-1"
    assert endpoint["url"] == "https://erp.example.com/hooks/kila"
    assert endpoint["is_active"] is True
    assert endpoint["secret_configured"] is True
    assert endpoint["event_subscriptions"] == ["document.approved", "event.approved"]


def test_register_webhook_endpoint_rejects_private_network_target(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/webhooks",
        headers={"X-API-Key": API_KEY},
        json={
            "url": "https://127.0.0.1/internal",
            "secret": "top-secret-webhook-key-000000000000",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "webhooks.non_public_address"


def test_update_webhook_endpoint_rotates_secret_and_can_disable_delivery(
    client: TestClient,
) -> None:
    created = client.post(
        "/v1/emitters/emitter-1/webhooks",
        headers={"X-API-Key": API_KEY},
        json={
            "url": "https://erp.example.com/hooks/old",
            "secret": "old-secret-webhook-key-000000000000",
        },
    )
    endpoint_id = created.json()["data"]["webhook_endpoint"]["id"]

    updated = client.patch(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}",
        headers={"X-API-Key": API_KEY},
        json={
            "url": "https://erp.example.com/hooks/new",
            "secret": "new-secret-webhook-key-000000000000",
            "event_subscriptions": ["document.rejected"],
            "is_active": False,
        },
    )

    assert updated.status_code == 200
    endpoint = updated.json()["data"]["webhook_endpoint"]
    assert endpoint["url"] == "https://erp.example.com/hooks/new"
    assert endpoint["event_subscriptions"] == ["document.rejected"]
    assert endpoint["is_active"] is False
    assert endpoint["secret_configured"] is True
    assert "secret" not in endpoint

    replay = client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}/deliveries/replay",
        headers={"X-API-Key": API_KEY},
        json={"event_type": "document.rejected", "payload": {}},
    )
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "webhooks.endpoint_inactive"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"url": "https://127.0.0.1/internal"},
        {"secret": "too-short"},
        {"is_active": None},
    ],
)
def test_update_webhook_endpoint_rejects_invalid_changes(
    client: TestClient,
    payload: dict,
) -> None:
    created = client.post(
        "/v1/emitters/emitter-1/webhooks",
        headers={"X-API-Key": API_KEY},
        json={
            "url": "https://erp.example.com/hooks/kila",
            "secret": "top-secret-webhook-key-000000000000",
        },
    )
    endpoint_id = created.json()["data"]["webhook_endpoint"]["id"]

    response = client.patch(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}",
        headers={"X-API-Key": API_KEY},
        json=payload,
    )

    assert response.status_code == 422


def test_replay_creates_delivery_and_job(client: TestClient) -> None:
    create_response = client.post(
        "/v1/emitters/emitter-1/webhooks",
        headers={"X-API-Key": API_KEY},
        json={
            "url": "https://erp.example.com/hooks/kila",
            "secret": "top-secret-webhook-key-000000000000",
            "event_subscriptions": ["document.approved"],
            "retry_policy": {"max_attempts": 3},
        },
    )
    endpoint_id = create_response.json()["data"]["webhook_endpoint"]["id"]

    replay_response = client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}/deliveries/replay",
        headers={"X-API-Key": API_KEY},
        json={
            "event_type": "document.approved",
            "payload": {"document_id": "doc-1", "status": "approved"},
        },
    )

    assert replay_response.status_code == 201
    data = replay_response.json()["data"]
    assert data["delivery"]["webhook_endpoint_id"] == endpoint_id
    assert data["delivery"]["event_type"] == "document.approved"
    assert data["delivery"]["final_status"] == "pending"
    assert data["job"]["job_type"] == "webhook.deliver"
    assert data["job"]["status"] == "queued"


def test_get_webhook_delivery_returns_delivery_and_job(client: TestClient) -> None:
    create_response = client.post(
        "/v1/emitters/emitter-1/webhooks",
        headers={"X-API-Key": API_KEY},
        json={
            "url": "https://erp.example.com/hooks/kila",
            "secret": "top-secret-webhook-key-000000000000",
            "event_subscriptions": ["document.approved"],
            "retry_policy": {"max_attempts": 3},
        },
    )
    endpoint_id = create_response.json()["data"]["webhook_endpoint"]["id"]
    replay_response = client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}/deliveries/replay",
        headers={"X-API-Key": API_KEY},
        json={
            "event_type": "document.approved",
            "payload": {"document_id": "doc-detail"},
        },
    )
    delivery_id = replay_response.json()["data"]["delivery"]["id"]

    response = client.get(
        f"/v1/emitters/emitter-1/webhook-deliveries/{delivery_id}",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["delivery"]["id"] == delivery_id
    assert data["job"]["related_entity_id"] == delivery_id
    assert data["job"]["job_type"] == "webhook.deliver"


def test_replay_webhook_delivery_returns_not_found_for_other_emitter(
    client: TestClient,
) -> None:
    second_emitter = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-c",
            "ruc": "80222222",
            "dv": "1",
            "legal_name": "EMITTER C SA",
            "tax_environment": "test",
            "csc": None,
            "csc_id": None,
        },
    ).json()["data"]["emitter"]["id"]
    create_response = client.post(
        f"/v1/emitters/{second_emitter}/webhooks",
        headers={"X-API-Key": API_KEY},
        json={
            "url": "https://erp.example.com/hooks/foreign",
            "secret": "top-secret-webhook-key-000000000000",
            "event_subscriptions": ["document.approved"],
            "retry_policy": {"max_attempts": 3},
        },
    )
    endpoint_id = create_response.json()["data"]["webhook_endpoint"]["id"]

    response = client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}/deliveries/replay",
        headers={"X-API-Key": API_KEY},
        json={
            "event_type": "document.approved",
            "payload": {"document_id": "doc-other"},
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "webhooks.endpoint_not_found"


def test_replay_webhook_delivery_requires_valid_api_key(client: TestClient) -> None:
    create_response = client.post(
        "/v1/emitters/emitter-1/webhooks",
        headers={"X-API-Key": API_KEY},
        json={
            "url": "https://erp.example.com/hooks/auth",
            "secret": "top-secret-webhook-key-000000000000",
            "event_subscriptions": ["document.approved"],
            "retry_policy": {"max_attempts": 3},
        },
    )
    endpoint_id = create_response.json()["data"]["webhook_endpoint"]["id"]

    response = client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}/deliveries/replay",
        headers={"X-API-Key": "wrong-key"},
        json={
            "event_type": "document.approved",
            "payload": {"document_id": "doc-auth"},
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.invalid_api_key"


def test_get_webhook_delivery_returns_not_found_for_other_emitter(
    client: TestClient,
) -> None:
    second_emitter = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-d",
            "ruc": "80333333",
            "dv": "2",
            "legal_name": "EMITTER D SA",
            "tax_environment": "test",
            "csc": None,
            "csc_id": None,
        },
    ).json()["data"]["emitter"]["id"]
    create_response = client.post(
        f"/v1/emitters/{second_emitter}/webhooks",
        headers={"X-API-Key": API_KEY},
        json={
            "url": "https://erp.example.com/hooks/foreign-detail",
            "secret": "top-secret-webhook-key-000000000000",
            "event_subscriptions": ["document.approved"],
            "retry_policy": {"max_attempts": 3},
        },
    )
    endpoint_id = create_response.json()["data"]["webhook_endpoint"]["id"]
    replay_response = client.post(
        f"/v1/emitters/{second_emitter}/webhooks/{endpoint_id}/deliveries/replay",
        headers={"X-API-Key": API_KEY},
        json={
            "event_type": "document.approved",
            "payload": {"document_id": "doc-foreign-detail"},
        },
    )
    delivery_id = replay_response.json()["data"]["delivery"]["id"]

    response = client.get(
        f"/v1/emitters/emitter-1/webhook-deliveries/{delivery_id}",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "webhooks.delivery_not_found"


def test_get_webhook_delivery_requires_valid_api_key(client: TestClient) -> None:
    create_response = client.post(
        "/v1/emitters/emitter-1/webhooks",
        headers={"X-API-Key": API_KEY},
        json={
            "url": "https://erp.example.com/hooks/auth-detail",
            "secret": "top-secret-webhook-key-000000000000",
            "event_subscriptions": ["document.approved"],
            "retry_policy": {"max_attempts": 3},
        },
    )
    endpoint_id = create_response.json()["data"]["webhook_endpoint"]["id"]
    replay_response = client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}/deliveries/replay",
        headers={"X-API-Key": API_KEY},
        json={
            "event_type": "document.approved",
            "payload": {"document_id": "doc-auth-detail"},
        },
    )
    delivery_id = replay_response.json()["data"]["delivery"]["id"]

    response = client.get(
        f"/v1/emitters/emitter-1/webhook-deliveries/{delivery_id}",
        headers={"X-API-Key": "wrong-key"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.invalid_api_key"


def test_list_webhook_deliveries_can_filter_by_emitter(client: TestClient) -> None:
    create_a = client.post(
        "/v1/emitters/emitter-1/webhooks",
        headers={"X-API-Key": API_KEY},
        json={
            "url": "https://erp.example.com/hooks/a",
            "secret": "top-secret-webhook-key-000000000000",
            "event_subscriptions": ["document.approved"],
            "retry_policy": {"max_attempts": 3},
        },
    )
    endpoint_a = create_a.json()["data"]["webhook_endpoint"]["id"]
    client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_a}/deliveries/replay",
        headers={"X-API-Key": API_KEY},
        json={
            "event_type": "document.approved",
            "payload": {"document_id": "doc-a"},
        },
    )

    second_emitter = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-b",
            "ruc": "80111111",
            "dv": "9",
            "legal_name": "EMITTER B SA",
            "tax_environment": "test",
            "csc": None,
            "csc_id": None,
        },
    ).json()["data"]["emitter"]["id"]
    create_b = client.post(
        f"/v1/emitters/{second_emitter}/webhooks",
        headers={"X-API-Key": API_KEY},
        json={
            "url": "https://erp.example.com/hooks/b",
            "secret": "top-secret-webhook-key-000000000000",
            "event_subscriptions": ["document.approved"],
            "retry_policy": {"max_attempts": 3},
        },
    )
    endpoint_b = create_b.json()["data"]["webhook_endpoint"]["id"]
    client.post(
        f"/v1/emitters/{second_emitter}/webhooks/{endpoint_b}/deliveries/replay",
        headers={"X-API-Key": API_KEY},
        json={
            "event_type": "document.approved",
            "payload": {"document_id": "doc-b"},
        },
    )

    listed = client.get(
        "/v1/webhook-deliveries?emitter_id=emitter-1&limit=20",
        headers={"X-API-Key": API_KEY},
    )

    assert listed.status_code == 200
    deliveries = listed.json()["data"]["deliveries"]
    assert len(deliveries) == 1
    assert deliveries[0]["payload_snapshot"]["data"]["document_id"] == "doc-a"


def test_list_webhook_deliveries_without_emitter_filter_returns_system_wide_data(
    client: TestClient,
) -> None:
    create_a = client.post(
        "/v1/emitters/emitter-1/webhooks",
        headers={"X-API-Key": API_KEY},
        json={
            "url": "https://erp.example.com/hooks/a-global",
            "secret": "top-secret-webhook-key-000000000000",
            "event_subscriptions": ["document.approved"],
            "retry_policy": {"max_attempts": 3},
        },
    )
    endpoint_a = create_a.json()["data"]["webhook_endpoint"]["id"]
    client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_a}/deliveries/replay",
        headers={"X-API-Key": API_KEY},
        json={
            "event_type": "document.approved",
            "payload": {"document_id": "doc-a-global"},
        },
    )

    second_emitter = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": "erp-b-global",
            "ruc": "80111111",
            "dv": "9",
            "legal_name": "EMITTER B SA",
            "tax_environment": "test",
            "csc": None,
            "csc_id": None,
        },
    ).json()["data"]["emitter"]["id"]
    create_b = client.post(
        f"/v1/emitters/{second_emitter}/webhooks",
        headers={"X-API-Key": API_KEY},
        json={
            "url": "https://erp.example.com/hooks/b-global",
            "secret": "top-secret-webhook-key-000000000000",
            "event_subscriptions": ["document.approved"],
            "retry_policy": {"max_attempts": 3},
        },
    )
    endpoint_b = create_b.json()["data"]["webhook_endpoint"]["id"]
    client.post(
        f"/v1/emitters/{second_emitter}/webhooks/{endpoint_b}/deliveries/replay",
        headers={"X-API-Key": API_KEY},
        json={
            "event_type": "document.approved",
            "payload": {"document_id": "doc-b-global"},
        },
    )

    listed = client.get(
        "/v1/webhook-deliveries?limit=20",
        headers={"X-API-Key": API_KEY},
    )

    assert listed.status_code == 200
    deliveries = listed.json()["data"]["deliveries"]
    delivered_doc_ids = {
        delivery["payload_snapshot"]["data"]["document_id"] for delivery in deliveries
    }
    assert "doc-a-global" in delivered_doc_ids
    assert "doc-b-global" in delivered_doc_ids


@pytest.mark.parametrize(
    "query",
    ["limit=0", "limit=101", "offset=-1"],
)
def test_list_webhook_deliveries_rejects_unbounded_pagination(
    client: TestClient,
    query: str,
) -> None:
    response = client.get(
        f"/v1/webhook-deliveries?{query}",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 422


def _seed_emitter(session_factory, encryption_key: str) -> None:
    emitter = Emitter(
        id="emitter-1",
        external_id="erp-ares",
        ruc="80024135",
        dv="5",
        legal_name="ARES PARAGUAY SRL",
        tax_environment="test",
        status="active",
        csc="ABCD0000000000000000000000000000",
        csc_id="0001",
        created_at=_now(),
        updated_at=_now(),
    )
    with session_scope(session_factory) as session:
        SqlAlchemyEmitterRepository(
            session,
            EncryptedCertificateStore(encryption_key),
        ).save(emitter)


def _now() -> datetime:
    return datetime.now(UTC)
