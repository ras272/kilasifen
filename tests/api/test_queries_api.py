from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kilasifen.api.app import create_app
from kilasifen.api.deps import get_query_service
from kilasifen.application.queries.service import QueryService
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
from kilasifen.infrastructure.db.session import build_engine, build_session_factory, session_scope
from kilasifen.infrastructure.sifen.query import DocumentQueryOutcome, RucQueryOutcome


API_KEY = "secret-key"


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    database_url = f"sqlite:///{tmp_path / 'queries.db'}"
    encryption_key = Fernet.generate_key().decode()
    monkeypatch.setenv("KILA_SIFEN_API_KEYS", f'["{API_KEY}"]')
    monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
    monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", encryption_key)

    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    _seed_query_context(
        session_factory=session_factory,
        certificate_store=EncryptedCertificateStore(encryption_key),
    )

    app = create_app()

    def _get_fake_query_service() -> QueryService:
        with session_scope(session_factory) as session:
            yield QueryService(
                emitter_repository=SqlAlchemyEmitterRepository(session),
                certificate_repository=SqlAlchemyCertificateRepository(session),
                document_repository=SqlAlchemyDocumentRepository(session),
                certificate_store=EncryptedCertificateStore(encryption_key),
                query_gateway=FakeQueryGateway(),
            )

    app.dependency_overrides[get_query_service] = _get_fake_query_service
    return TestClient(app)


def test_query_ruc_returns_normalized_business_payload(client: TestClient) -> None:
    response = client.get(
        "/v1/emitters/emitter-1/queries/ruc/80024135-5",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    payload = response.json()["data"]["ruc_query"]
    assert payload["queried_ruc"] == "80024135"
    assert payload["status"] == "found"
    assert payload["result_code"] == "0300"
    assert payload["result_message"] == "Consulta exitosa"
    assert payload["taxpayer"]["ruc"] == "80024135"
    assert payload["taxpayer"]["legal_name"] == "ARES PARAGUAY SRL"
    assert payload["taxpayer"]["state_code"] == "ACT"
    assert payload["taxpayer"]["state"] == "Activo"
    assert payload["taxpayer"]["electronic_taxpayer"] is True


def test_query_document_returns_normalized_payload_and_persists_trace(
    client: TestClient,
) -> None:
    response = client.get(
        "/v1/emitters/emitter-1/queries/documents/document-1",
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    payload = response.json()["data"]["document_query"]
    assert payload["document_id"] == "document-1"
    assert payload["cdc"] == "01800123450001001001001012026042411234567891"
    assert payload["status"] == "found"
    assert payload["result_code"] == "0300"
    assert payload["result_message"] == "Consulta DE exitosa"
    assert payload["content_xml"] == "<rDE version='150'/>"

    engine = build_engine(get_settings().database_url)
    session_factory = build_session_factory(engine)
    with session_scope(session_factory) as session:
        document = SqlAlchemyDocumentRepository(session).get("document-1")

    assert document is not None
    assert document.last_query_request_xml == "<query-document-request/>"
    assert document.last_query_response_raw == "<query-document-response/>"
    assert document.sifen_status == "found"
    assert document.sifen_result_code == "0300"
    assert document.sifen_result_message == "Consulta DE exitosa"
    assert document.last_query_at is not None


@dataclass(slots=True)
class FakeQueryGateway:
    def query_ruc(self, **kwargs) -> RucQueryOutcome:
        return RucQueryOutcome(
            queried_ruc="80024135",
            request_xml="<query-ruc-request/>",
            response_raw="<query-ruc-response/>",
            result_code="0300",
            result_message="Consulta exitosa",
            status="found",
            taxpayer_ruc="80024135",
            taxpayer_legal_name="ARES PARAGUAY SRL",
            taxpayer_state_code="ACT",
            taxpayer_state="Activo",
            electronic_taxpayer=True,
        )

    def query_document(self, **kwargs) -> DocumentQueryOutcome:
        return DocumentQueryOutcome(
            cdc="01800123450001001001001012026042411234567891",
            request_xml="<query-document-request/>",
            response_raw="<query-document-response/>",
            result_code="0300",
            result_message="Consulta DE exitosa",
            status="found",
            content_xml="<rDE version='150'/>",
            processed_at=datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
        )


def _seed_query_context(
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
