from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.api.deps import get_webhook_service
from kilasifen.application.webhooks.service import WebhookService
from kilasifen.config import get_settings
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.webhooks.models import WebhookDelivery
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
        json={"delivery_id": "any-delivery"},
    )
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "webhooks.endpoint_inactive"

    ping = client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}/test",
        headers={"X-API-Key": API_KEY},
    )
    assert ping.status_code == 409
    assert ping.json()["error"]["code"] == "webhooks.endpoint_inactive"


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


def test_replay_redelivers_an_existing_event_with_a_new_delivery_id(
    client: TestClient,
) -> None:
    endpoint_id = _register_endpoint(client, "emitter-1", "replay")
    source = _publish_event(
        client,
        emitter_id="emitter-1",
        event_type="document.approved",
        payload={"document_id": "doc-1", "internal_status": "approved"},
    )

    replay_response = client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}/deliveries/replay",
        headers={"X-API-Key": API_KEY},
        json={"delivery_id": source.id},
    )

    assert replay_response.status_code == 201
    data = replay_response.json()["data"]
    delivery = data["delivery"]
    assert delivery["id"] != source.id
    assert delivery["webhook_endpoint_id"] == endpoint_id
    assert delivery["event_type"] == "document.approved"
    assert delivery["final_status"] == "pending"
    assert delivery["payload_snapshot"] == {
        "type": "document.approved",
        "delivery_id": delivery["id"],
        "occurred_at": source.payload_snapshot["occurred_at"],
        "data": {"document_id": "doc-1", "internal_status": "approved"},
    }
    assert data["job"]["job_type"] == "webhook.deliver"
    assert data["job"]["status"] == "queued"


@pytest.mark.parametrize(
    "body",
    [
        {"event_type": "document.approved", "payload": {"document_id": "forged"}},
        {"delivery_id": "x", "event_type": "document.approved"},
        {"delivery_id": "x", "payload": {"document_id": "forged"}},
        {},
    ],
)
def test_replay_rejects_caller_supplied_event_content(
    client: TestClient,
    body: dict,
) -> None:
    endpoint_id = _register_endpoint(client, "emitter-1", "forgery")

    response = client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}/deliveries/replay",
        headers={"X-API-Key": API_KEY},
        json=body,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request.validation_failed"


def test_replay_returns_not_found_for_unknown_delivery(client: TestClient) -> None:
    endpoint_id = _register_endpoint(client, "emitter-1", "unknown-delivery")

    response = client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}/deliveries/replay",
        headers={"X-API-Key": API_KEY},
        json={"delivery_id": "does-not-exist"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "webhooks.delivery_not_found"


def test_replay_cannot_copy_a_delivery_of_another_emitter(
    client: TestClient,
) -> None:
    second_emitter = _create_emitter(client, "erp-replay-foreign", "80444444", "3")
    _register_endpoint(client, second_emitter, "foreign-source")
    foreign = _publish_event(
        client,
        emitter_id=second_emitter,
        event_type="document.approved",
        payload={"document_id": "foreign-doc"},
    )
    endpoint_id = _register_endpoint(client, "emitter-1", "own-target")

    response = client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}/deliveries/replay",
        headers={"X-API-Key": API_KEY},
        json={"delivery_id": foreign.id},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "webhooks.delivery_not_found"


def test_replay_refuses_a_delivery_without_a_complete_event_snapshot(
    client: TestClient,
) -> None:
    endpoint_id = _register_endpoint(client, "emitter-1", "legacy")
    source = _publish_event(
        client,
        emitter_id="emitter-1",
        event_type="document.approved",
        payload={"document_id": "doc-legacy"},
    )
    with session_scope(client.app.state.session_factory) as session:
        SqlAlchemyWebhookRepository(session).save_delivery(
            replace(source, payload_snapshot=None)
        )

    response = client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}/deliveries/replay",
        headers={"X-API-Key": API_KEY},
        json={"delivery_id": source.id},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "webhooks.delivery_not_replayable"


def test_send_test_event_delivers_a_marked_synthetic_event(
    client: TestClient,
) -> None:
    endpoint_id = _register_endpoint(client, "emitter-1", "ping")

    response = client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}/test",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["delivery"]["event_type"] == "webhook.test"
    assert data["delivery"]["payload_snapshot"]["data"] == {
        "test": True,
        "endpoint_id": endpoint_id,
    }
    assert data["job"]["job_type"] == "webhook.deliver"


def test_send_test_event_returns_not_found_for_other_emitter_endpoint(
    client: TestClient,
) -> None:
    second_emitter = _create_emitter(client, "erp-ping-foreign", "80555555", "4")
    endpoint_id = _register_endpoint(client, second_emitter, "foreign-ping")

    response = client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}/test",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "webhooks.endpoint_not_found"


def test_get_webhook_delivery_returns_delivery_and_job(client: TestClient) -> None:
    _register_endpoint(client, "emitter-1", "detail")
    delivery_id = _publish_event(
        client,
        emitter_id="emitter-1",
        event_type="document.approved",
        payload={"document_id": "doc-detail"},
    ).id

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
    second_emitter = _create_emitter(client, "erp-c", "80222222", "1")
    endpoint_id = _register_endpoint(client, second_emitter, "foreign")

    response = client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}/deliveries/replay",
        headers={"X-API-Key": API_KEY},
        json={"delivery_id": "any-delivery"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "webhooks.endpoint_not_found"


def test_replay_webhook_delivery_requires_valid_api_key(client: TestClient) -> None:
    endpoint_id = _register_endpoint(client, "emitter-1", "auth")

    response = client.post(
        f"/v1/emitters/emitter-1/webhooks/{endpoint_id}/deliveries/replay",
        headers={"X-API-Key": "wrong-key"},
        json={"delivery_id": "any-delivery"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.invalid_api_key"


def test_get_webhook_delivery_returns_not_found_for_other_emitter(
    client: TestClient,
) -> None:
    second_emitter = _create_emitter(client, "erp-d", "80333333", "2")
    _register_endpoint(client, second_emitter, "foreign-detail")
    delivery_id = _publish_event(
        client,
        emitter_id=second_emitter,
        event_type="document.approved",
        payload={"document_id": "doc-foreign-detail"},
    ).id

    response = client.get(
        f"/v1/emitters/emitter-1/webhook-deliveries/{delivery_id}",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "webhooks.delivery_not_found"


def test_get_webhook_delivery_requires_valid_api_key(client: TestClient) -> None:
    _register_endpoint(client, "emitter-1", "auth-detail")
    delivery_id = _publish_event(
        client,
        emitter_id="emitter-1",
        event_type="document.approved",
        payload={"document_id": "doc-auth-detail"},
    ).id

    response = client.get(
        f"/v1/emitters/emitter-1/webhook-deliveries/{delivery_id}",
        headers={"X-API-Key": "wrong-key"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.invalid_api_key"


def test_list_webhook_deliveries_can_filter_by_emitter(client: TestClient) -> None:
    _register_endpoint(client, "emitter-1", "a")
    _publish_event(
        client,
        emitter_id="emitter-1",
        event_type="document.approved",
        payload={"document_id": "doc-a"},
    )
    second_emitter = _create_emitter(client, "erp-b", "80111111", "9")
    _register_endpoint(client, second_emitter, "b")
    _publish_event(
        client,
        emitter_id=second_emitter,
        event_type="document.approved",
        payload={"document_id": "doc-b"},
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
    _register_endpoint(client, "emitter-1", "a-global")
    _publish_event(
        client,
        emitter_id="emitter-1",
        event_type="document.approved",
        payload={"document_id": "doc-a-global"},
    )
    second_emitter = _create_emitter(client, "erp-b-global", "80111111", "9")
    _register_endpoint(client, second_emitter, "b-global")
    _publish_event(
        client,
        emitter_id=second_emitter,
        event_type="document.approved",
        payload={"document_id": "doc-b-global"},
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


def _create_emitter(client: TestClient, external_id: str, ruc: str, dv: str) -> str:
    response = client.post(
        "/v1/emitters",
        headers={"X-API-Key": API_KEY},
        json={
            "external_id": external_id,
            "ruc": ruc,
            "dv": dv,
            "legal_name": f"EMITTER {external_id.upper()} SA",
            "tax_environment": "test",
            "csc": None,
            "csc_id": None,
        },
    )
    assert response.status_code == 201
    return response.json()["data"]["emitter"]["id"]


def _register_endpoint(client: TestClient, emitter_id: str, name: str) -> str:
    response = client.post(
        f"/v1/emitters/{emitter_id}/webhooks",
        headers={"X-API-Key": API_KEY},
        json={
            "url": f"https://erp.example.com/hooks/{name}",
            "secret": "top-secret-webhook-key-000000000000",
            "event_subscriptions": ["document.approved"],
            "retry_policy": {"max_attempts": 3},
        },
    )
    assert response.status_code == 201
    return response.json()["data"]["webhook_endpoint"]["id"]


def _publish_event(
    client: TestClient,
    *,
    emitter_id: str,
    event_type: str,
    payload: dict,
) -> WebhookDelivery:
    """Generate a delivery the way the platform does, outside the public API."""

    encryption_key = get_settings().encryption_key
    with session_scope(client.app.state.session_factory) as session:
        service = WebhookService(
            webhook_repository=SqlAlchemyWebhookRepository(session),
            emitter_repository=SqlAlchemyEmitterRepository(
                session,
                EncryptedCertificateStore(encryption_key),
            ),
            job_repository=SqlAlchemyJobRepository(session),
            secret_store=EncryptedCertificateStore(encryption_key),
            queue=_NoopWebhookQueue(),
            deliverer=WebhookDeliverer(
                sender=lambda *_args, **_kwargs: None,
                url_policy=WebhookUrlPolicy(
                    resolver=lambda _host, _port: ["93.184.216.34"]
                ),
            ),
        )
        published = service.publish_event(
            emitter_id=emitter_id,
            event_type=event_type,
            payload=payload,
        )
    assert len(published) == 1
    return published[0][0]


class _NoopWebhookQueue:
    def enqueue_webhook_delivery(self, *args, **kwargs):
        del args, kwargs
        return None


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
    return datetime.now(timezone.utc)
