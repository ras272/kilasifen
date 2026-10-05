"""Raw-route document creation: the XML policy only gates new documents."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from kilasifen.application.documents.service import DocumentService
from kilasifen.application.jobs.service import JobService
from kilasifen.domain.common.errors import ConflictError, UnprocessableEntityError
from kilasifen.domain.emitters.models import Emitter
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.repositories.documents import (
    SqlAlchemyDocumentRepository,
)
from kilasifen.infrastructure.db.repositories.emitters import (
    SqlAlchemyEmitterRepository,
)
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from kilasifen.infrastructure.sifen.raw_xml_policy import (
    require_signable_raw_payload,
)
from kilasifen.testing.database import managed_test_database_url
from tests._raw_xml import golden_signed_xml, raw_document_payload

# Shape of a raw document created before the XML policy existed.
_PRE_POLICY_PAYLOAD = {"signed_xml": golden_signed_xml()}
_SCHEMA_INVALID_RDE = (
    "<rDE xmlns='http://ekuatia.set.gov.py/sifen/xsd'>"
    "<dVerFor>150</dVerFor><DE Id='A1'/></rDE>"
)


def test_raw_retry_of_a_pre_policy_document_replays_it(tmp_path) -> None:
    with _document_service(tmp_path, "raw_replay") as (service, documents):
        legacy, legacy_job, _ = service.create_document(
            emitter_id="emitter-1",
            external_id="erp-legacy",
            idempotency_key="idem-legacy",
            document_type="factura",
            payload_snapshot=_PRE_POLICY_PAYLOAD,
        )

        replayed, replayed_job, was_replayed = service.create_raw_document(
            emitter_id="emitter-1",
            external_id="erp-legacy",
            idempotency_key="idem-legacy",
            document_type="factura",
            payload_snapshot=_PRE_POLICY_PAYLOAD,
        )
        document_count = len(documents.list_recent(limit=10))

    assert was_replayed is True
    assert replayed.id == legacy.id
    assert replayed_job.id == legacy_job.id
    assert document_count == 1


def test_raw_retry_without_key_of_a_pre_policy_document_conflicts(tmp_path) -> None:
    with _document_service(tmp_path, "raw_external") as (service, _documents):
        service.create_document(
            emitter_id="emitter-1",
            external_id="erp-legacy",
            idempotency_key=None,
            document_type="factura",
            payload_snapshot=_PRE_POLICY_PAYLOAD,
        )

        with pytest.raises(ConflictError) as raised:
            service.create_raw_document(
                emitter_id="emitter-1",
                external_id="erp-legacy",
                idempotency_key=None,
                document_type="factura",
                payload_snapshot=_PRE_POLICY_PAYLOAD,
            )

    assert raised.value.code == "documents.external_id_conflict"


def test_new_raw_document_with_signed_xml_is_rejected(tmp_path) -> None:
    with _document_service(tmp_path, "raw_rejected") as (service, documents):
        with pytest.raises(UnprocessableEntityError) as raised:
            service.create_raw_document(
                emitter_id="emitter-1",
                external_id="erp-new",
                idempotency_key="idem-new",
                document_type="factura",
                payload_snapshot=_PRE_POLICY_PAYLOAD,
            )
        document_count = len(documents.list_recent(limit=10))

    assert raised.value.code == "documents.raw.signed_xml_not_allowed"
    assert document_count == 0


def test_new_raw_document_reports_schema_errors_as_details(tmp_path) -> None:
    payload = {"generated_xml": _SCHEMA_INVALID_RDE}
    with _document_service(tmp_path, "raw_schema") as (service, _documents):
        with pytest.raises(UnprocessableEntityError) as raised:
            service.create_raw_document(
                emitter_id="emitter-1",
                external_id="erp-schema",
                idempotency_key=None,
                document_type="factura",
                payload_snapshot=payload,
            )

    assert raised.value.code == "documents.raw.generated_xml_invalid_schema"
    assert raised.value.details["errors"]


def test_new_raw_document_with_valid_xml_is_created(tmp_path) -> None:
    with _document_service(tmp_path, "raw_created") as (service, _documents):
        document, _job, was_replayed = service.create_raw_document(
            emitter_id="emitter-1",
            external_id="erp-valid",
            idempotency_key="idem-valid",
            document_type="factura",
            payload_snapshot=raw_document_payload(),
        )

    assert was_replayed is False
    assert document.payload_snapshot["generated_xml"]


def test_raw_document_creation_fails_closed_without_a_policy(tmp_path) -> None:
    with _document_service(
        tmp_path, "raw_no_policy", raw_payload_policy=None
    ) as (service, documents):
        with pytest.raises(RuntimeError):
            service.create_raw_document(
                emitter_id="emitter-1",
                external_id="erp-valid",
                idempotency_key="idem-valid",
                document_type="factura",
                payload_snapshot=raw_document_payload(),
            )
        document_count = len(documents.list_recent(limit=10))

    assert document_count == 0


@contextmanager
def _document_service(
    tmp_path,
    name: str,
    *,
    raw_payload_policy=require_signable_raw_payload,
) -> Iterator[tuple[DocumentService, SqlAlchemyDocumentRepository]]:
    with managed_test_database_url(tmp_path=tmp_path, name=name) as database_url:
        engine = build_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = build_session_factory(engine)
        with session_scope(session_factory) as session:
            emitter_repository = SqlAlchemyEmitterRepository(session)
            document_repository = SqlAlchemyDocumentRepository(session)
            emitter_repository.save(_emitter())
            service = DocumentService(
                document_repository=document_repository,
                emitter_repository=emitter_repository,
                job_service=JobService(SqlAlchemyJobRepository(session)),
                raw_payload_policy=raw_payload_policy,
            )
            yield service, document_repository


def _emitter() -> Emitter:
    now = datetime.now(timezone.utc)
    return Emitter(
        id="emitter-1",
        external_id="erp-ares",
        ruc="80024135",
        dv="5",
        legal_name="ARES PARAGUAY SRL",
        tax_environment="test",
        status="active",
        csc=None,
        csc_id=None,
        created_at=now,
        updated_at=now,
    )
