from collections.abc import Iterator
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import kilasifen.application.events.service as event_service_module
from kilasifen.api.app import create_app
from kilasifen.api.deps import get_event_service
from kilasifen.application.events.service import EventService
from kilasifen.config import get_settings
from kilasifen.domain.certificates.models import Certificate
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.events.models import Event
from kilasifen.domain.jobs.models import Job
from kilasifen.domain.stampings.models import Stamping
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.models import DocumentNumberingSequenceModel
from kilasifen.infrastructure.db.repositories.certificates import (
    SqlAlchemyCertificateRepository,
)
from kilasifen.infrastructure.db.repositories.documents import (
    SqlAlchemyDocumentRepository,
)
from kilasifen.infrastructure.db.repositories.emitters import (
    SqlAlchemyEmitterRepository,
)
from kilasifen.infrastructure.db.repositories.events import SqlAlchemyEventRepository
from kilasifen.infrastructure.db.repositories.inutilized_number_ranges import (
    SqlAlchemyInutilizedNumberRangeRepository,
)
from kilasifen.infrastructure.db.repositories.job_outbox import (
    SqlAlchemyJobOutboxRepository,
)
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.repositories.stampings import (
    SqlAlchemyStampingRepository,
)
from kilasifen.infrastructure.db.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from kilasifen.infrastructure.jobs.workers import process_event_job
from kilasifen.infrastructure.sifen.event import (
    EventSubmissionOutcome,
    PreparedEventSubmission,
)
from kilasifen.testing.database import managed_test_database_url

API_KEY = "secret-key"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def published_webhooks() -> list[dict]:
    return []


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    published_webhooks: list[dict],
) -> Iterator[TestClient]:
    with managed_test_database_url(tmp_path=tmp_path, name="events") as database_url:
        encryption_key = Fernet.generate_key().decode()
        monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{API_KEY}"]')
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", encryption_key)
        monkeypatch.setattr(
            event_service_module,
            "build_signed_cancel_event_group_xml",
            lambda **_: "<gGroupGesEve/>",
        )
        monkeypatch.setattr(
            event_service_module,
            "build_signed_inutilization_event_group_xml",
            lambda **_: "<gGroupGesEve/>",
        )

        engine = build_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = build_session_factory(engine)
        _seed_event_context(
            session_factory=session_factory,
            certificate_store=EncryptedCertificateStore(encryption_key),
        )

        app = create_app()

        def _get_fake_event_service():
            with session_scope(session_factory) as session:
                yield EventService(
                    event_repository=SqlAlchemyEventRepository(session),
                    emitter_repository=SqlAlchemyEmitterRepository(
                        session,
                        EncryptedCertificateStore(encryption_key),
                    ),
                    document_repository=SqlAlchemyDocumentRepository(session),
                    certificate_repository=SqlAlchemyCertificateRepository(session),
                    job_repository=SqlAlchemyJobRepository(session),
                    certificate_store=EncryptedCertificateStore(encryption_key),
                    submission_gateway=FakeEventGateway(),
                    inutilized_range_repository=SqlAlchemyInutilizedNumberRangeRepository(
                        session
                    ),
                    stamping_repository=SqlAlchemyStampingRepository(session),
                    webhook_publisher=FakeWebhookPublisher(published_webhooks),
                )

        app.dependency_overrides[get_event_service] = _get_fake_event_service
        with TestClient(app) as test_client:
            yield test_client


def test_create_event_over_document_returns_event_and_job(client: TestClient) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/events",
        headers={"X-API-Key": API_KEY},
        json={
            "document_id": "doc-fe-recent",
            "event_type": "cancelacion",
            "payload": {
                "event_xml": (
                    "<gGroupGesEve "
                    "xmlns='http://ekuatia.set.gov.py/sifen/xsd' />"
                )
            },
        },
    )

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["event"]["document_id"] == "doc-fe-recent"
    assert body["event"]["event_type"] == "cancelacion"
    assert body["event"]["status"] == "approved"
    assert body["job"]["related_entity_type"] == "event"
    assert body["job"]["status"] == "succeeded"


def test_get_event_returns_event_and_job(client: TestClient) -> None:
    create_response = client.post(
        "/v1/emitters/emitter-1/events",
        headers={"X-API-Key": API_KEY},
        json={
            "document_id": "doc-fe-recent",
            "event_type": "cancelacion",
            "payload": {
                "event_xml": (
                    "<gGroupGesEve "
                    "xmlns='http://ekuatia.set.gov.py/sifen/xsd' />"
                )
            },
        },
    )
    event_id = create_response.json()["data"]["event"]["id"]

    response = client.get(
        f"/v1/emitters/emitter-1/events/{event_id}",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["event"]["id"] == event_id
    assert body["job"]["related_entity_id"] == event_id
    assert body["job"]["job_type"] == "event.submit"


def test_get_event_returns_not_found_for_other_emitter(client: TestClient) -> None:
    create_response = client.post(
        "/v1/emitters/emitter-2/events",
        headers={"X-API-Key": API_KEY},
        json={
            "document_id": "doc-emitter-2",
            "event_type": "cancelacion",
            "payload": {
                "event_xml": (
                    "<gGroupGesEve "
                    "xmlns='http://ekuatia.set.gov.py/sifen/xsd' />"
                )
            },
        },
    )
    event_id = create_response.json()["data"]["event"]["id"]

    response = client.get(
        f"/v1/emitters/emitter-1/events/{event_id}",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "events.not_found"


def test_get_event_requires_valid_api_key(client: TestClient) -> None:
    create_response = client.post(
        "/v1/emitters/emitter-1/events",
        headers={"X-API-Key": API_KEY},
        json={
            "document_id": "doc-fe-recent",
            "event_type": "cancelacion",
            "payload": {
                "event_xml": (
                    "<gGroupGesEve "
                    "xmlns='http://ekuatia.set.gov.py/sifen/xsd' />"
                )
            },
        },
    )
    event_id = create_response.json()["data"]["event"]["id"]

    response = client.get(
        f"/v1/emitters/emitter-1/events/{event_id}",
        headers={"X-API-Key": "wrong-key"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth.invalid_api_key"


def test_cancel_factura_within_48h_succeeds_and_publishes_webhook(
    client: TestClient,
    published_webhooks: list[dict],
) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/documents/doc-fe-recent/cancel",
        headers={"X-API-Key": API_KEY},
        json={"motivo": "Cancelacion por error de carga"},
    )

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["event"]["status"] == "approved"
    assert any(
        item["event_type"] == "document.cancelled" for item in published_webhooks
    )


def test_cancel_nota_credito_within_168h_succeeds(client: TestClient) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/documents/doc-nc-recent/cancel",
        headers={"X-API-Key": API_KEY},
        json={"motivo": "Cancelacion por devolucion"},
    )
    assert response.status_code == 201
    assert response.json()["data"]["event"]["status"] == "approved"


def test_cancel_factura_after_48h_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/documents/doc-fe-old/cancel",
        headers={"X-API-Key": API_KEY},
        json={"motivo": "Fuera de plazo permitido"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "events.cancel.deadline_exceeded"


def test_cancel_nota_credito_after_168h_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/documents/doc-nc-old/cancel",
        headers={"X-API-Key": API_KEY},
        json={"motivo": "Fuera de plazo permitido"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "events.cancel.deadline_exceeded"


def test_cancel_non_approved_document_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/documents/doc-not-approved/cancel",
        headers={"X-API-Key": API_KEY},
        json={"motivo": "Intento cancelacion no aprobada"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "events.cancel.document_not_approved"


def test_cancel_already_cancelled_document_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/documents/doc-cancelled/cancel",
        headers={"X-API-Key": API_KEY},
        json={"motivo": "Intento duplicado"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "events.cancel.already_cancelled"


def test_cancel_rejects_when_child_dte_not_cancelled(client: TestClient) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/documents/doc-parent/cancel",
        headers={"X-API-Key": API_KEY},
        json={"motivo": "Cancelacion de factura padre"},
    )

    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "events.cancel.child_dte_not_cancelled"
    assert body["details"]["child_cdcs"] == [
        "01800123450001001000040112026042012345678901"
    ]


def test_the_cancel_window_counts_from_the_approval_in_sifen(
    client: TestClient,
) -> None:
    """DECISIONES F71: sifen_approved_at, not the last update of the row."""

    response = client.post(
        "/v1/emitters/emitter-1/documents/doc-fe-touched/cancel",
        headers={"X-API-Key": API_KEY},
        json={"motivo": "Fuera de plazo desde la aprobacion"},
    )

    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "events.cancel.deadline_exceeded"
    assert body["details"]["approved_at_source"] == "sifen"
    assert body["details"]["remedy"] == "nota_credito"


def test_a_second_cancellation_waits_for_the_pending_one(client: TestClient) -> None:
    """DECISIONES F70: a second request would be a duplicate (4003)."""

    response = client.post(
        "/v1/emitters/emitter-1/documents/doc-fe-pending-cancel/cancel",
        headers={"X-API-Key": API_KEY},
        json={"motivo": "Segundo intento de cancelacion"},
    )

    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "events.cancel.already_pending"
    assert body["details"]["event_ids"] == ["event-pending-cancel"]


def test_rejected_failed_and_queued_children_do_not_block_the_cancellation(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/documents/doc-parent-of-rejected/cancel",
        headers={"X-API-Key": API_KEY},
        json={"motivo": "Hijos que no son DTE"},
    )

    assert response.status_code == 201
    assert response.json()["data"]["event"]["status"] == "approved"


def test_a_child_that_may_be_at_sifen_blocks_the_cancellation(
    client: TestClient,
) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/documents/doc-parent-of-in-flight/cancel",
        headers={"X-API-Key": API_KEY},
        json={"motivo": "Hijo en vuelo"},
    )

    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "events.cancel.child_dte_not_cancelled"
    assert body["details"]["child_cdcs"] == [
        "01800123450001001000100112026042012345678901"
    ]


@pytest.mark.parametrize(
    ("child_status", "retryable_server_error", "job_status", "blocks"),
    [
        # The same signed DE travels again after a 0420 (DECISIONES F63).
        ("queued", False, "retry_scheduled", True),
        # A rejection 0161/0162 being sent again (DECISIONES F64).
        ("rejected", True, "retry_scheduled", True),
        # Attempts exhausted: only an operator retry would send it.
        ("rejected", True, "failed", False),
        ("queued", False, "failed", False),
    ],
)
def test_a_child_about_to_travel_blocks_the_cancellation(
    client: TestClient,
    child_status: str,
    retryable_server_error: bool,
    job_status: str,
    blocks: bool,
) -> None:
    """MT v150 Tabla J p. 117: the associated DTE are cancelled first."""

    parent_cdc = "01800123450001001000200012026042012345678901"
    child_cdc = "01800123450001001000200112026042012345678901"
    with session_scope(_session_factory()) as session:
        documents = SqlAlchemyDocumentRepository(session)
        documents.save(
            _document(
                id="doc-parent-of-resend",
                emitter_id="emitter-1",
                document_type="factura",
                cdc=parent_cdc,
                sifen_status="approved",
                internal_status="approved",
                updated_at=_now() - timedelta(hours=3),
            )
        )
        documents.save(
            replace(
                _document(
                    id="doc-child-resend",
                    emitter_id="emitter-1",
                    document_type="nota_credito",
                    cdc=child_cdc,
                    sifen_status=child_status,
                    internal_status=child_status,
                    payload_snapshot={
                        "typed_contract": {
                            "contract": "nota_credito_v1",
                            "payload": {"documento_asociado": {"cdc": parent_cdc}},
                        }
                    },
                    updated_at=_now() - timedelta(hours=1),
                ),
                retryable_server_error=retryable_server_error,
            )
        )
        SqlAlchemyJobRepository(session).save(
            Job(
                id="job-doc-child-resend",
                emitter_id="emitter-1",
                related_entity_type="document",
                related_entity_id="doc-child-resend",
                job_type="document.emit",
                status=job_status,
                attempts=1,
                error_snapshot=None,
                scheduled_at=_now(),
                started_at=_now(),
                finished_at=None,
                worker_correlation_id=None,
                created_at=_now(),
                updated_at=_now(),
            )
        )

    response = client.post(
        "/v1/emitters/emitter-1/documents/doc-parent-of-resend/cancel",
        headers={"X-API-Key": API_KEY},
        json={"motivo": "Hijo por reenviar"},
    )

    if blocks:
        assert response.status_code == 409
        body = response.json()["error"]
        assert body["code"] == "events.cancel.child_dte_not_cancelled"
        assert body["details"]["child_cdcs"] == [child_cdc]
    else:
        assert response.status_code == 201


def test_cancel_cross_emitter_returns_404(client: TestClient) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/documents/doc-emitter-2/cancel",
        headers={"X-API-Key": API_KEY},
        json={"motivo": "No debe poder cancelar"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "documents.not_found"


def test_inutilization_success_publishes_webhook(
    client: TestClient,
    published_webhooks: list[dict],
) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/inutilizations",
        headers={"X-API-Key": API_KEY},
        json={
            "timbrado": "80024135",
            "document_type": "factura",
            "establishment": "001",
            "point": "001",
            "numero_desde": 30,
            "numero_hasta": 35,
            "motivo": "Rango no utilizado por contingencia",
        },
    )
    assert response.status_code == 201
    assert response.json()["data"]["event"]["status"] == "approved"
    assert any(
        item["event_type"] == "numbering.inutilized" for item in published_webhooks
    )


def test_inutilization_rejects_used_range(client: TestClient) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/inutilizations",
        headers={"X-API-Key": API_KEY},
        json={
            "timbrado": "80024135",
            "document_type": "factura",
            "establishment": "001",
            "point": "001",
            "numero_desde": 10,
            "numero_hasta": 15,
            "motivo": "Rango ya utilizado",
        },
    )
    assert response.status_code == 409
    body = response.json()["error"]
    assert body["code"] == "events.inutilize.range_already_used"
    assert body["details"]["collisions"] == [12]


def test_inutilization_rejects_inverted_range(client: TestClient) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/inutilizations",
        headers={"X-API-Key": API_KEY},
        json={
            "timbrado": "80024135",
            "document_type": "factura",
            "establishment": "001",
            "point": "001",
            "numero_desde": 20,
            "numero_hasta": 19,
            "motivo": "Rango invertido",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "events.inutilize.invalid_range"


def test_inutilization_rejects_range_larger_than_1000(client: TestClient) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/inutilizations",
        headers={"X-API-Key": API_KEY},
        json={
            "timbrado": "80024135",
            "document_type": "factura",
            "establishment": "001",
            "point": "001",
            "numero_desde": 1,
            "numero_hasta": 1005,
            "motivo": "Rango demasiado grande",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "events.inutilize.range_too_large"


def test_inutilization_rejects_overlapping_approved_range(client: TestClient) -> None:
    first = client.post(
        "/v1/emitters/emitter-1/inutilizations",
        headers={"X-API-Key": API_KEY},
        json={
            "timbrado": "80024135",
            "document_type": "factura",
            "establishment": "001",
            "point": "002",
            "numero_desde": 40,
            "numero_hasta": 45,
            "motivo": "Primera inutilizacion",
        },
    )
    assert first.status_code == 201

    second = client.post(
        "/v1/emitters/emitter-1/inutilizations",
        headers={"X-API-Key": API_KEY},
        json={
            "timbrado": "80024135",
            "document_type": "factura",
            "establishment": "001",
            "point": "002",
            "numero_desde": 44,
            "numero_hasta": 50,
            "motivo": "Solapa rango anterior",
        },
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "events.inutilize.range_already_inutilized"


def test_inutilization_isolation_between_emitters(client: TestClient) -> None:
    first = client.post(
        "/v1/emitters/emitter-1/inutilizations",
        headers={"X-API-Key": API_KEY},
        json={
            "timbrado": "80024135",
            "document_type": "factura",
            "establishment": "001",
            "point": "004",
            "numero_desde": 1,
            "numero_hasta": 5,
            "motivo": "Rango emisor A",
        },
    )
    assert first.status_code == 201

    second = client.post(
        "/v1/emitters/emitter-2/inutilizations",
        headers={"X-API-Key": API_KEY},
        json={
            "timbrado": "90000001",
            "document_type": "factura",
            "establishment": "001",
            "point": "004",
            "numero_desde": 1,
            "numero_hasta": 5,
            "motivo": "Mismo rango, otro emisor",
        },
    )
    assert second.status_code == 201


def test_an_old_sequence_no_longer_blocks_an_inutilization(
    client: TestClient,
) -> None:
    """DECISIONES F72: there is no 45-day cap; SIFEN has no deadline code."""

    response = client.post(
        "/v1/emitters/emitter-1/inutilizations",
        headers={"X-API-Key": API_KEY},
        json={
            "timbrado": "80024135",
            "document_type": "factura",
            "establishment": "001",
            "point": "003",
            "numero_desde": 10,
            "numero_hasta": 15,
            "motivo": "Rango historico sin documentos",
        },
    )
    assert response.status_code == 201
    assert response.json()["data"]["warnings"] == []


def _inutilize(client: TestClient, **overrides) -> object:
    body = {
        "timbrado": "80024135",
        "document_type": "factura",
        "establishment": "002",
        "point": "001",
        "numero_desde": 1,
        "numero_hasta": 5,
        "motivo": "Numeros que no se van a usar",
    }
    body.update(overrides)
    return client.post(
        "/v1/emitters/emitter-1/inutilizations",
        headers={"X-API-Key": API_KEY},
        json=body,
    )


def test_rejected_failed_and_aborted_numbers_are_inutilized(
    client: TestClient,
    published_webhooks: list[dict],
) -> None:
    """MT v150 §11.1.1; Dto 872/2023 Arts. 29 and 31 (DECISIONES F72)."""

    response = _inutilize(client)

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["event"]["status"] == "approved"
    payload = body["event"]["input_payload"]["typed_contract"]["payload"]
    assert sorted(payload["document_ids"]) == [
        "doc-num-aborted",
        "doc-num-failed",
        "doc-num-rejected",
    ]
    webhook = next(
        item
        for item in published_webhooks
        if item["event_type"] == "numbering.inutilized"
    )
    assert sorted(webhook["payload"]["document_ids"]) == sorted(
        payload["document_ids"]
    )
    with session_scope(_session_factory()) as session:
        documents = SqlAlchemyDocumentRepository(session)
        statuses = {
            document_id: documents.get(document_id).internal_status
            for document_id in payload["document_ids"]
        }
    assert set(statuses.values()) == {"inutilized"}


def test_a_late_inutilization_is_flagged_not_refused(client: TestClient) -> None:
    response = _inutilize(client)

    body = response.json()["data"]
    payload = body["event"]["input_payload"]["typed_contract"]["payload"]
    # The earliest number was consumed in January 2026: day 15 of February.
    assert payload["deadline"] == "2026-02-15"
    assert payload["extemporaneous"] is True
    assert body["warnings"] == ["inutilization.extemporaneous"]


@pytest.mark.parametrize(
    ("numero", "status"),
    [
        (10, "approved"),
        (11, "cancelled"),
        (12, "retry_pending"),
        (13, "rejected"),
    ],
)
def test_dte_and_documents_that_may_be_at_sifen_block_the_range(
    client: TestClient,
    numero: int,
    status: str,
) -> None:
    # 13 is rejected but its job will still send it again.
    response = _inutilize(client, numero_desde=numero, numero_hasta=numero)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "events.inutilize.range_already_used"
    assert error["details"]["collisions"] == [numero]
    assert error["details"]["documents"][0]["status"] == status


def test_documents_of_another_timbrado_do_not_collide(client: TestClient) -> None:
    response = _inutilize(
        client, timbrado="80024136", numero_desde=10, numero_hasta=10
    )

    assert response.status_code == 201


def _save_legacy_document(document_id: str, numero: int, status: str) -> None:
    """A document signed under timbrado 80024135 before ``timbrado`` existed."""

    signed = (
        "<rDE><DE><gTimb><dNumTim>80024135</dNumTim></gTimb></DE>"
        "<Signature/></rDE>"
    )
    with session_scope(_session_factory()) as session:
        SqlAlchemyDocumentRepository(session).save(
            replace(
                _document(
                    id=document_id,
                    emitter_id="emitter-1",
                    document_type="factura",
                    cdc=None,
                    sifen_status=status,
                    internal_status=status,
                    establishment="002",
                    point="001",
                    document_number=numero,
                    updated_at=_now() - timedelta(days=1),
                ),
                signed_xml=signed,
            )
        )


def test_a_legacy_document_counts_only_for_its_own_timbrado(
    client: TestClient,
    published_webhooks: list[dict],
) -> None:
    """1109 applies per timbrado (MT v150 §12.4 C007 p. 161).

    Without a recorded timbrado, the ``dNumTim`` of the signed XML decides:
    inutilizing the same number of another timbrado neither collides with
    the document nor marks it ``inutilized``.
    """

    _save_legacy_document("doc-legacy-approved", 20, "approved")
    _save_legacy_document("doc-legacy-rejected", 21, "rejected")

    response = _inutilize(
        client, timbrado="80024136", numero_desde=20, numero_hasta=21
    )

    assert response.status_code == 201
    payload = response.json()["data"]["event"]["input_payload"]["typed_contract"][
        "payload"
    ]
    assert payload["document_ids"] == []
    with session_scope(_session_factory()) as session:
        documents = SqlAlchemyDocumentRepository(session)
        assert documents.get("doc-legacy-approved").internal_status == "approved"
        assert documents.get("doc-legacy-rejected").internal_status == "rejected"

    # Under its own timbrado the rejected number is inutilized as usual.
    response = _inutilize(client, numero_desde=21, numero_hasta=21)

    assert response.status_code == 201
    with session_scope(_session_factory()) as session:
        document = SqlAlchemyDocumentRepository(session).get("doc-legacy-rejected")
    assert document.internal_status == "inutilized"


def test_the_timbrado_must_belong_to_the_emitter(client: TestClient) -> None:
    response = _inutilize(client, timbrado="12345678")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "events.inutilize.unknown_timbrado"


def test_the_series_must_be_two_capital_letters(client: TestClient) -> None:
    response = _inutilize(client, serie="a1")

    assert response.status_code == 422


def test_cancel_is_queued_then_worker_applies_approved_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path, name="event_worker"
    ) as database_url:
        encryption_key = Fernet.generate_key().decode()
        store = EncryptedCertificateStore(encryption_key)
        engine = build_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = build_session_factory(engine)
        _seed_event_context(
            session_factory=session_factory,
            certificate_store=store,
        )
        monkeypatch.setattr(
            event_service_module,
            "build_signed_cancel_event_group_xml",
            lambda **_: "<gGroupGesEve/>",
        )
        queue = RecordingEventQueue()

        with session_scope(session_factory) as session:
            service = EventService(
                event_repository=SqlAlchemyEventRepository(session),
                emitter_repository=SqlAlchemyEmitterRepository(session, store),
                document_repository=SqlAlchemyDocumentRepository(session),
                certificate_repository=SqlAlchemyCertificateRepository(session),
                job_repository=SqlAlchemyJobRepository(session),
                certificate_store=store,
                submission_gateway=NeverCalledEventGateway(),
                inutilized_range_repository=(
                    SqlAlchemyInutilizedNumberRangeRepository(session)
                ),
                queue=queue,
                database_url=database_url,
                encryption_key=encryption_key,
            )
            event, job = service.cancel_document(
                emitter_id="emitter-1",
                document_id="doc-fe-recent",
                motivo="Cancelacion asincrona segura",
            )
            assert event.status == "queued"
            assert job.status == "queued"
            assert queue.job_ids == [job.id]

        payload = process_event_job(
            job_id=job.id,
            database_url=database_url,
            encryption_key=encryption_key,
            submission_gateway=FakeEventGateway(),
        )

        assert payload["event_status"] == "approved"
        assert payload["job_status"] == "succeeded"
        with session_scope(session_factory) as session:
            document = SqlAlchemyDocumentRepository(session).get("doc-fe-recent")
            assert document is not None
            assert document.internal_status == "cancelled"
            persisted_job = SqlAlchemyJobRepository(session).get(job.id)
            assert persisted_job is not None
            assert persisted_job.attempts == 1


def test_event_worker_stages_retry_in_the_same_database_transaction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path, name="event_worker_retry"
    ) as database_url:
        encryption_key = Fernet.generate_key().decode()
        store = EncryptedCertificateStore(encryption_key)
        engine = build_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = build_session_factory(engine)
        _seed_event_context(
            session_factory=session_factory,
            certificate_store=store,
        )
        monkeypatch.setattr(
            event_service_module,
            "build_signed_cancel_event_group_xml",
            lambda **_: "<gGroupGesEve/>",
        )

        with session_scope(session_factory) as session:
            service = EventService(
                event_repository=SqlAlchemyEventRepository(session),
                emitter_repository=SqlAlchemyEmitterRepository(session, store),
                document_repository=SqlAlchemyDocumentRepository(session),
                certificate_repository=SqlAlchemyCertificateRepository(session),
                job_repository=SqlAlchemyJobRepository(session),
                certificate_store=store,
                submission_gateway=NeverCalledEventGateway(),
                inutilized_range_repository=(
                    SqlAlchemyInutilizedNumberRangeRepository(session)
                ),
                queue=RecordingEventQueue(),
                database_url=database_url,
                encryption_key=encryption_key,
            )
            _event, job = service.cancel_document(
                emitter_id="emitter-1",
                document_id="doc-fe-recent",
                motivo="Reintento durable",
            )

        payload = process_event_job(
            job_id=job.id,
            database_url=database_url,
            encryption_key=encryption_key,
            submission_gateway=PendingEventGateway(),
        )

        assert payload["retryable"] is True
        assert payload["job_status"] == "retry_scheduled"
        with session_scope(session_factory) as session:
            persisted_job = SqlAlchemyJobRepository(session).get(job.id)
            outbox = SqlAlchemyJobOutboxRepository(session).get_for_job(job.id)
        assert persisted_job is not None
        assert persisted_job.scheduled_at is not None
        assert outbox is not None and outbox.status == "pending"
        assert outbox.available_at == persisted_job.scheduled_at


class FakeEventGateway:
    """Prepares the stored event as is and answers with ``outcome``."""

    def __init__(self, outcome: EventSubmissionOutcome | None = None) -> None:
        self.outcome = outcome or EventSubmissionOutcome(
            response_raw="<event-response/>",
            status="approved",
            result_code="0600",
            result_message="Evento registrado correctamente",
            protocol="90001234",
        )
        self.submitted_requests: list[str] = []

    def prepare_event(self, *, event, **kwargs) -> PreparedEventSubmission:
        del kwargs
        return PreparedEventSubmission(
            signed_xml=event.generated_xml,
            request_xml=f"<event-request id='{event.id}'/>",
        )

    def submit_prepared(self, *, request_xml: str, **kwargs) -> EventSubmissionOutcome:
        del kwargs
        self.submitted_requests.append(request_xml)
        return self.outcome


class NeverCalledEventGateway:
    def prepare_event(self, **kwargs) -> PreparedEventSubmission:
        del kwargs
        raise AssertionError("HTTP request must not submit an event to SIFEN")

    submit_prepared = prepare_event


class PendingEventGateway(FakeEventGateway):
    def __init__(self) -> None:
        super().__init__(
            EventSubmissionOutcome(
                response_raw="<event-response/>",
                status="submitted",
                result_code="0300",
                result_message="Procesamiento pendiente",
                protocol=None,
            )
        )


class RecordingEventQueue:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    def enqueue_event_submit(self, job, **kwargs):
        del kwargs
        self.job_ids.append(job.id)
        return None


class FakeWebhookPublisher:
    def __init__(self, sink: list[dict]):
        self.sink = sink

    def publish_event(self, *, emitter_id: str, event_type: str, payload: dict | None):
        self.sink.append(
            {
                "emitter_id": emitter_id,
                "event_type": event_type,
                "payload": payload,
            }
        )
        return []


def _seed_event_context(
    *,
    session_factory,
    certificate_store: EncryptedCertificateStore,
) -> None:
    with session_scope(session_factory) as session:
        emitter_repo = SqlAlchemyEmitterRepository(session, certificate_store)
        cert_repo = SqlAlchemyCertificateRepository(session)
        doc_repo = SqlAlchemyDocumentRepository(session)

        emitter_repo.save(
            Emitter(
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
        )
        emitter_repo.save(
            Emitter(
                id="emitter-2",
                external_id="erp-otro",
                ruc="80111111",
                dv="9",
                legal_name="OTRO EMISOR SA",
                tax_environment="test",
                status="active",
                csc="ABCD0000000000000000000000000000",
                csc_id="0001",
                created_at=_now(),
                updated_at=_now(),
            )
        )

        cert_repo.save(
            Certificate(
                id="cert-1",
                emitter_id="emitter-1",
                logical_name="principal",
                encrypted_p12=certificate_store.encrypt_bytes(b"fake-cert"),
                encrypted_password=certificate_store.encrypt_text("secret"),
                fingerprint="fingerprint",
                serial_number=None,
                subject_summary=None,
                detected_ruc="80024135",
                valid_from=None,
                valid_until=None,
                is_active=True,
                status="uploaded",
                created_at=_now(),
                updated_at=_now(),
            )
        )
        cert_repo.save(
            Certificate(
                id="cert-2",
                emitter_id="emitter-2",
                logical_name="principal",
                encrypted_p12=certificate_store.encrypt_bytes(b"fake-cert"),
                encrypted_password=certificate_store.encrypt_text("secret"),
                fingerprint="fingerprint",
                serial_number=None,
                subject_summary=None,
                detected_ruc="80111111",
                valid_from=None,
                valid_until=None,
                is_active=True,
                status="uploaded",
                created_at=_now(),
                updated_at=_now(),
            )
        )

        doc_repo.save(
            _document(
                id="doc-fe-recent",
                emitter_id="emitter-1",
                document_type="factura",
                cdc="01800123450001001000010012026042012345678901",
                sifen_status="approved",
                internal_status="approved",
                updated_at=_now() - timedelta(hours=24),
            )
        )
        doc_repo.save(
            _document(
                id="doc-fe-old",
                emitter_id="emitter-1",
                document_type="factura",
                cdc="01800123450001001000010112026042012345678901",
                sifen_status="approved",
                internal_status="approved",
                updated_at=_now() - timedelta(hours=49),
            )
        )
        doc_repo.save(
            _document(
                id="doc-nc-recent",
                emitter_id="emitter-1",
                document_type="nota_credito",
                cdc="01800123450001001000020012026042012345678901",
                sifen_status="approved_with_observation",
                internal_status="approved_with_observation",
                updated_at=_now() - timedelta(hours=72),
            )
        )
        doc_repo.save(
            _document(
                id="doc-nc-old",
                emitter_id="emitter-1",
                document_type="nota_credito",
                cdc="01800123450001001000020112026042012345678901",
                sifen_status="approved",
                internal_status="approved",
                updated_at=_now() - timedelta(hours=169),
            )
        )
        doc_repo.save(
            _document(
                id="doc-not-approved",
                emitter_id="emitter-1",
                document_type="factura",
                cdc=None,
                sifen_status="queued",
                internal_status="queued",
                updated_at=_now(),
            )
        )
        doc_repo.save(
            _document(
                id="doc-cancelled",
                emitter_id="emitter-1",
                document_type="factura",
                cdc="01800123450001001000030012026042012345678901",
                sifen_status="cancelled",
                internal_status="cancelled",
                updated_at=_now(),
            )
        )
        parent_cdc = "01800123450001001000040012026042012345678901"
        doc_repo.save(
            _document(
                id="doc-parent",
                emitter_id="emitter-1",
                document_type="factura",
                cdc=parent_cdc,
                sifen_status="approved",
                internal_status="approved",
                updated_at=_now() - timedelta(hours=12),
            )
        )
        doc_repo.save(
            _document(
                id="doc-child",
                emitter_id="emitter-1",
                document_type="nota_credito",
                cdc="01800123450001001000040112026042012345678901",
                sifen_status="approved",
                internal_status="approved",
                payload_snapshot={
                    "typed_contract": {
                        "contract": "nota_credito_v1",
                        "payload": {"documento_asociado": {"cdc": parent_cdc}},
                    }
                },
                updated_at=_now() - timedelta(hours=6),
            )
        )
        doc_repo.save(
            _document(
                id="doc-used-number",
                emitter_id="emitter-1",
                document_type="factura",
                cdc="01800123450001001000050012026042012345678901",
                sifen_status="approved",
                internal_status="approved",
                establishment="001",
                point="001",
                document_number=12,
                updated_at=_now(),
            )
        )
        doc_repo.save(
            _document(
                id="doc-emitter-2",
                emitter_id="emitter-2",
                document_type="factura",
                cdc="01801111190001001000060012026042012345678901",
                sifen_status="approved",
                internal_status="approved",
                updated_at=_now(),
            )
        )
        # Touched a minute ago, approved by SIFEN 49 h ago (DECISIONES F71).
        doc_repo.save(
            _document(
                id="doc-fe-touched",
                emitter_id="emitter-1",
                document_type="factura",
                cdc="01800123450001001000070012026042012345678901",
                sifen_status="approved",
                internal_status="approved",
                updated_at=_now(),
                sifen_approved_at=_now() - timedelta(hours=49),
            )
        )
        doc_repo.save(
            _document(
                id="doc-fe-pending-cancel",
                emitter_id="emitter-1",
                document_type="factura",
                cdc="01800123450001001000080012026042012345678901",
                sifen_status="approved",
                internal_status="approved",
                updated_at=_now() - timedelta(hours=2),
            )
        )
        SqlAlchemyEventRepository(session).save(
            Event(
                id="event-pending-cancel",
                emitter_id="emitter-1",
                document_id="doc-fe-pending-cancel",
                event_type="cancel_document",
                input_payload=None,
                generated_xml="<gGroupGesEve/>",
                signed_xml="<gGroupGesEve/>",
                sifen_request_xml="<rEnviEventoDe/>",
                sifen_response_raw=None,
                status="retry_pending",
                sifen_result_code=None,
                sifen_result_message="timeout",
                created_at=_now(),
                updated_at=_now(),
            )
        )
        children_parent_cdc = "01800123450001001000090012026042012345678901"
        doc_repo.save(
            _document(
                id="doc-parent-of-rejected",
                emitter_id="emitter-1",
                document_type="factura",
                cdc=children_parent_cdc,
                sifen_status="approved",
                internal_status="approved",
                updated_at=_now() - timedelta(hours=3),
            )
        )
        rejected_child_cdc = "01800123450001001000090112026042012345678901"
        for child_id, child_status, child_cdc in (
            ("doc-child-rejected", "rejected", rejected_child_cdc),
            ("doc-child-failed", "failed", None),
            ("doc-child-queued", "queued", None),
        ):
            doc_repo.save(
                _document(
                    id=child_id,
                    emitter_id="emitter-1",
                    document_type="nota_credito",
                    cdc=child_cdc,
                    sifen_status=child_status,
                    internal_status=child_status,
                    payload_snapshot={
                        "typed_contract": {
                            "contract": "nota_credito_v1",
                            "payload": {
                                "documento_asociado": {"cdc": children_parent_cdc}
                            },
                        }
                    },
                    updated_at=_now() - timedelta(hours=1),
                )
            )
        in_flight_parent_cdc = "01800123450001001000100012026042012345678901"
        doc_repo.save(
            _document(
                id="doc-parent-of-in-flight",
                emitter_id="emitter-1",
                document_type="factura",
                cdc=in_flight_parent_cdc,
                sifen_status="approved",
                internal_status="approved",
                updated_at=_now() - timedelta(hours=3),
            )
        )
        doc_repo.save(
            _document(
                id="doc-child-in-flight",
                emitter_id="emitter-1",
                document_type="nota_credito",
                cdc="01800123450001001000100112026042012345678901",
                sifen_status="retry_pending",
                internal_status="retry_pending",
                payload_snapshot={
                    "typed_contract": {
                        "contract": "nota_credito_v1",
                        "payload": {
                            "documento_asociado": {"cdc": in_flight_parent_cdc}
                        },
                    }
                },
                updated_at=_now() - timedelta(hours=1),
            )
        )

        for stamping_id, emitter_id, number in (
            ("stamp-1", "emitter-1", "80024135"),
            ("stamp-1b", "emitter-1", "80024136"),
            ("stamp-2", "emitter-2", "90000001"),
        ):
            SqlAlchemyStampingRepository(session).save(
                Stamping(
                    id=stamping_id,
                    emitter_id=emitter_id,
                    number=number,
                    start_date=date(2024, 1, 1),
                    end_date=None,
                    is_active=stamping_id != "stamp-1b",
                    status="active",
                    created_at=_now(),
                    updated_at=_now(),
                )
            )
        _seed_numbered_documents(doc_repo, SqlAlchemyJobRepository(session))

        session.add(
            DocumentNumberingSequenceModel(
                id="seq-old-1",
                emitter_id="emitter-1",
                establishment="001",
                point="003",
                document_type="factura",
                last_number=100,
                updated_at=_now() - timedelta(days=46),
            )
        )


def _session_factory():
    return build_session_factory(build_engine(get_settings().database_url))


def _seed_numbered_documents(doc_repo, job_repo) -> None:
    """Numbers 1-5 and 10-13 of 002-001 (timbrado 80024135), for F72."""

    consumed = datetime(2026, 1, 20, 15, 0, tzinfo=timezone.utc)
    cdc_prefix = "0180012345000200100000"
    cdc_suffix = "2026012012345678901"
    rows = (
        # number, status, job status, cdc
        (1, "rejected", "failed", f"{cdc_prefix}011{cdc_suffix}"),
        (2, "failed", "failed", None),
        (3, "queued", "failed", None),
        (10, "approved", "succeeded", f"{cdc_prefix}101{cdc_suffix}"),
        (11, "cancelled", "succeeded", f"{cdc_prefix}111{cdc_suffix}"),
        (12, "retry_pending", "retry_scheduled", f"{cdc_prefix}121{cdc_suffix}"),
        (13, "rejected", "retry_scheduled", f"{cdc_prefix}131{cdc_suffix}"),
    )
    names = {1: "rejected", 2: "failed", 3: "aborted"}
    for number, status, job_status, cdc in rows:
        document_id = f"doc-num-{names.get(number, number)}"
        doc_repo.save(
            replace(
                _document(
                    id=document_id,
                    emitter_id="emitter-1",
                    document_type="factura",
                    cdc=cdc,
                    sifen_status=status,
                    internal_status=status,
                    establishment="002",
                    point="001",
                    document_number=number,
                    updated_at=consumed + timedelta(days=number),
                    timbrado="80024135",
                ),
                created_at=consumed + timedelta(days=number),
            )
        )
        job_repo.save(
            Job(
                id=f"job-{document_id}",
                emitter_id="emitter-1",
                related_entity_type="document",
                related_entity_id=document_id,
                job_type="document.emit",
                status=job_status,
                attempts=1,
                error_snapshot=None,
                scheduled_at=consumed,
                started_at=consumed,
                finished_at=None,
                worker_correlation_id=None,
                created_at=consumed,
                updated_at=consumed,
            )
        )


def _document(
    *,
    id: str,
    emitter_id: str,
    document_type: str,
    cdc: str | None,
    sifen_status: str | None,
    internal_status: str,
    updated_at: datetime,
    payload_snapshot: dict | None = None,
    establishment: str | None = None,
    point: str | None = None,
    document_number: int | None = None,
    sifen_approved_at: datetime | None = None,
    timbrado: str | None = None,
) -> Document:
    return Document(
        id=id,
        emitter_id=emitter_id,
        external_id=f"ext-{id}",
        idempotency_key=f"idem-{id}",
        document_type=document_type,
        payload_snapshot=payload_snapshot,
        generated_xml="<rDE/>",
        signed_xml="<rDE><Signature/></rDE>",
        sifen_request_xml="<emit-request/>",
        sifen_response_raw="<emit-response/>",
        last_query_request_xml=None,
        last_query_response_raw=None,
        last_query_at=None,
        cdc=cdc,
        internal_status=internal_status,
        sifen_status=sifen_status,
        sifen_result_code="0260" if sifen_status else None,
        sifen_result_message="ok" if sifen_status else None,
        created_at=updated_at - timedelta(minutes=1),
        updated_at=updated_at,
        establishment=establishment,
        point=point,
        document_number=document_number,
        sifen_approved_at=sifen_approved_at,
        timbrado=timbrado,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
