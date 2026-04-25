from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.api.deps import get_event_service
from kilasifen.application.events.service import EventService
from kilasifen.config import get_settings
from kilasifen.domain.certificates.models import Certificate
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.repositories.certificates import (
    SqlAlchemyCertificateRepository,
)
from kilasifen.infrastructure.db.repositories.documents import SqlAlchemyDocumentRepository
from kilasifen.infrastructure.db.repositories.emitters import SqlAlchemyEmitterRepository
from kilasifen.infrastructure.db.repositories.events import SqlAlchemyEventRepository
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.session import build_engine, build_session_factory, session_scope
from kilasifen.infrastructure.sifen.event import EventSubmissionOutcome


API_KEY = "secret-key"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    database_url = f"sqlite:///{tmp_path / 'events.db'}"
    encryption_key = Fernet.generate_key().decode()
    monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{API_KEY}"]')
    monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
    monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", encryption_key)

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
            )

    app.dependency_overrides[get_event_service] = _get_fake_event_service
    return TestClient(app)


def test_create_event_over_document_returns_event_and_job(client: TestClient) -> None:
    response = client.post(
        "/v1/emitters/emitter-1/events",
        headers={"X-API-Key": API_KEY},
        json={
            "document_id": "document-1",
            "event_type": "cancelacion",
            "payload": {
                "event_xml": "<gGroupGesEve xmlns='http://ekuatia.set.gov.py/sifen/xsd' />"
            },
        },
    )

    assert response.status_code == 201
    body = response.json()["data"]
    event = body["event"]
    job = body["job"]

    assert event["document_id"] == "document-1"
    assert event["event_type"] == "cancelacion"
    assert event["status"] == "approved"
    assert event["sifen_result_code"] == "0300"
    assert event["sifen_result_message"] == "Evento procesado"
    assert event["sifen_request_xml"] == "<event-request/>"
    assert event["sifen_response_raw"] == "<event-response/>"
    assert job["related_entity_type"] == "event"
    assert job["status"] == "succeeded"


def test_get_event_returns_event_and_job(client: TestClient) -> None:
    create_response = client.post(
        "/v1/emitters/emitter-1/events",
        headers={"X-API-Key": API_KEY},
        json={
            "document_id": "document-1",
            "event_type": "cancelacion",
            "payload": {
                "event_xml": "<gGroupGesEve xmlns='http://ekuatia.set.gov.py/sifen/xsd' />"
            },
        },
    )
    event_id = create_response.json()["data"]["event"]["id"]

    response = client.get(
        f"/v1/events/{event_id}",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["event"]["id"] == event_id
    assert body["event"]["status"] == "approved"
    assert body["job"]["related_entity_id"] == event_id
    assert body["job"]["job_type"] == "event.submit"


class FakeEventGateway:
    def submit_event(self, **kwargs) -> EventSubmissionOutcome:
        return EventSubmissionOutcome(
            generated_xml=kwargs["event"].generated_xml,
            signed_xml=None,
            request_xml="<event-request/>",
            response_raw="<event-response/>",
            status="approved",
            result_code="0300",
            result_message="Evento procesado",
        )


def _seed_event_context(
    *,
    session_factory,
    certificate_store: EncryptedCertificateStore,
) -> None:
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
    certificate = Certificate(
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
    document = Document(
        id="document-1",
        emitter_id="emitter-1",
        external_id="erp-doc-1",
        idempotency_key="idem-1",
        document_type="factura",
        payload_snapshot={"total": "100000"},
        generated_xml="<rDE/>",
        signed_xml="<rDE><Signature/></rDE>",
        sifen_request_xml="<emit-request/>",
        sifen_response_raw="<emit-response/>",
        last_query_request_xml=None,
        last_query_response_raw=None,
        last_query_at=None,
        cdc="01800123450001001001001012026042411234567891",
        internal_status="approved",
        sifen_status="approved",
        sifen_result_code="0260",
        sifen_result_message="Autorizacion satisfactoria",
        created_at=_now(),
        updated_at=_now(),
    )

    with session_scope(session_factory) as session:
        SqlAlchemyEmitterRepository(session).save(emitter)
        SqlAlchemyCertificateRepository(session).save(certificate)
        SqlAlchemyDocumentRepository(session).save(document)


def _now() -> datetime:
    return datetime.now(UTC)
