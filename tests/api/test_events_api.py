from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.api.deps import get_event_service
import kilasifen.application.events.service as event_service_module
from kilasifen.application.events.service import EventService
from kilasifen.config import get_settings
from kilasifen.domain.certificates.models import Certificate
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.models import DocumentNumberingSequenceModel
from kilasifen.infrastructure.db.repositories.certificates import SqlAlchemyCertificateRepository
from kilasifen.infrastructure.db.repositories.document_numbering_sequences import (
    SqlAlchemyDocumentNumberingSequenceRepository,
)
from kilasifen.infrastructure.db.repositories.documents import SqlAlchemyDocumentRepository
from kilasifen.infrastructure.db.repositories.emitters import SqlAlchemyEmitterRepository
from kilasifen.infrastructure.db.repositories.events import SqlAlchemyEventRepository
from kilasifen.infrastructure.db.repositories.inutilized_number_ranges import (
    SqlAlchemyInutilizedNumberRangeRepository,
)
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.session import build_engine, build_session_factory, session_scope
from kilasifen.infrastructure.sifen.event import EventSubmissionOutcome
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
                    emitter_repository=SqlAlchemyEmitterRepository(session),
                    document_repository=SqlAlchemyDocumentRepository(session),
                    certificate_repository=SqlAlchemyCertificateRepository(session),
                    job_repository=SqlAlchemyJobRepository(session),
                    certificate_store=EncryptedCertificateStore(encryption_key),
                    submission_gateway=FakeEventGateway(),
                    numbering_repository=SqlAlchemyDocumentNumberingSequenceRepository(session),
                    inutilized_range_repository=SqlAlchemyInutilizedNumberRangeRepository(session),
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
                "event_xml": "<gGroupGesEve xmlns='http://ekuatia.set.gov.py/sifen/xsd' />"
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
                "event_xml": "<gGroupGesEve xmlns='http://ekuatia.set.gov.py/sifen/xsd' />"
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
                "event_xml": "<gGroupGesEve xmlns='http://ekuatia.set.gov.py/sifen/xsd' />"
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
                "event_xml": "<gGroupGesEve xmlns='http://ekuatia.set.gov.py/sifen/xsd' />"
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
    assert any(item["event_type"] == "document.cancelled" for item in published_webhooks)


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
    assert body["details"]["child_cdcs"] == ["01800123450001001000040112026042012345678901"]


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
    assert any(item["event_type"] == "numbering.inutilized" for item in published_webhooks)


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


def test_inutilization_deadline_exceeded_when_sequence_is_too_old(client: TestClient) -> None:
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
            "motivo": "Rango historico fuera de plazo",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "events.inutilize.deadline_exceeded"


class FakeEventGateway:
    def submit_event(self, **kwargs) -> EventSubmissionOutcome:
        return EventSubmissionOutcome(
            generated_xml=kwargs["event"].generated_xml,
            signed_xml=kwargs["event"].generated_xml,
            request_xml="<event-request/>",
            response_raw="<event-response/>",
            status="approved",
            result_code="0300",
            result_message="Evento procesado",
            protocol="90001234",
        )


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
        emitter_repo = SqlAlchemyEmitterRepository(session)
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
    )


def _now() -> datetime:
    return datetime.now(UTC)
