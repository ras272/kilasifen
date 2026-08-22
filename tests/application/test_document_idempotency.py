from copy import deepcopy
from datetime import UTC, datetime

import pytest

from kilasifen.application.documents.service import DocumentService
from kilasifen.application.jobs.service import JobService
from kilasifen.domain.common.errors import ConflictError
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
from kilasifen.testing.database import managed_test_database_url


def test_create_document_is_idempotent_per_emitter_and_key(tmp_path) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="document_idempotency_a",
    ) as database_url:
        engine = build_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = build_session_factory(engine)

        emitter = Emitter(
            id="emitter-1",
            external_id="erp-ares",
            ruc="80024135",
            dv="5",
            legal_name="ARES PARAGUAY SRL",
            tax_environment="test",
            status="active",
            csc=None,
            csc_id=None,
            created_at=_now(),
            updated_at=_now(),
        )

        with session_scope(session_factory) as session:
            emitter_repository = SqlAlchemyEmitterRepository(session)
            document_repository = SqlAlchemyDocumentRepository(session)
            job_repository = SqlAlchemyJobRepository(session)
            emitter_repository.save(emitter)

            job_service = JobService(job_repository)
            service = DocumentService(
                document_repository=document_repository,
                emitter_repository=emitter_repository,
                job_service=job_service,
            )

            first_document, first_job, first_replayed = service.create_document(
                emitter_id=emitter.id,
                external_id="erp-doc-1",
                idempotency_key="idem-1",
                document_type="factura",
                payload_snapshot={"total": "100000", "currency": "PYG"},
            )
            second_document, second_job, second_replayed = service.create_document(
                emitter_id=emitter.id,
                external_id="erp-doc-1",
                idempotency_key="idem-1",
                document_type="factura",
                payload_snapshot={"currency": "PYG", "total": "100000"},
            )

            with pytest.raises(ConflictError) as payload_conflict:
                service.create_document(
                    emitter_id=emitter.id,
                    external_id="erp-doc-1",
                    idempotency_key="idem-1",
                    document_type="factura",
                    payload_snapshot={"total": "200000", "currency": "PYG"},
                )
            with pytest.raises(ConflictError) as type_conflict:
                service.create_document(
                    emitter_id=emitter.id,
                    external_id="erp-doc-1",
                    idempotency_key="idem-1",
                    document_type="nota_credito",
                    payload_snapshot={"total": "100000", "currency": "PYG"},
                )
            document_count = len(document_repository.list_recent(limit=10))
            job_count = len(job_repository.list_recent(limit=10))

        assert second_document.id == first_document.id
        assert second_job.id == first_job.id
        assert first_replayed is False
        assert second_replayed is True
        assert str(payload_conflict.value) == "documents.idempotency_key_conflict"
        assert payload_conflict.value.details == {
            "existing_document_id": first_document.id,
            "mismatched_parameters": ["payload"],
        }
        assert str(type_conflict.value) == "documents.idempotency_key_conflict"
        assert type_conflict.value.details == {
            "existing_document_id": first_document.id,
            "mismatched_parameters": ["document_type"],
        }
        assert document_count == 1
        assert job_count == 1


def test_numbered_typed_document_replay_ignores_server_assigned_number(
    tmp_path,
) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="document_idempotency_numbered",
    ) as database_url:
        engine = build_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = build_session_factory(engine)
        numbering = _FixedNumberingService()

        with session_scope(session_factory) as session:
            emitter_repository = SqlAlchemyEmitterRepository(session)
            document_repository = SqlAlchemyDocumentRepository(session)
            job_repository = SqlAlchemyJobRepository(session)
            emitter = _emitter()
            emitter_repository.save(emitter)
            service = DocumentService(
                document_repository=document_repository,
                emitter_repository=emitter_repository,
                job_service=JobService(job_repository),
                numbering_service=numbering,
            )
            intent = {
                "generated_xml": None,
                "signed_xml": None,
                "doc_id": None,
                "typed_contract": {
                    "contract": "factura_v1",
                    "payload": {
                        "establecimiento": 1,
                        "punto": "001",
                        "numero": 999,
                        "total": "100000",
                    },
                },
            }

            first, first_job, first_replayed = service.create_document(
                emitter_id=emitter.id,
                external_id="erp-numbered-1",
                idempotency_key="idem-numbered-1",
                document_type="factura",
                payload_snapshot=intent,
            )
            replay, replay_job, replayed = service.create_document(
                emitter_id=emitter.id,
                external_id="erp-numbered-1",
                idempotency_key="idem-numbered-1",
                document_type="factura",
                payload_snapshot=intent,
            )
            conflicting_intent = deepcopy(intent)
            conflicting_intent["typed_contract"]["payload"]["total"] = "200000"
            with pytest.raises(ConflictError) as conflict:
                service.create_document(
                    emitter_id=emitter.id,
                    external_id="erp-numbered-1",
                    idempotency_key="idem-numbered-1",
                    document_type="factura",
                    payload_snapshot=conflicting_intent,
                )

        assert first_replayed is False
        assert replayed is True
        assert replay.id == first.id
        assert replay_job.id == first_job.id
        assert first.document_number == 42
        assert numbering.calls == 1
        assert conflict.value.details == {
            "existing_document_id": first.id,
            "mismatched_parameters": ["payload"],
        }


def test_create_document_enqueues_job_when_queue_is_configured(tmp_path) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="document_idempotency_b",
    ) as database_url:
        engine = build_engine(database_url)
        Base.metadata.create_all(engine)
        session_factory = build_session_factory(engine)
        queue = _FakeDocumentQueue()

        emitter = Emitter(
            id="emitter-1",
            external_id="erp-ares",
            ruc="80024135",
            dv="5",
            legal_name="ARES PARAGUAY SRL",
            tax_environment="test",
            status="active",
            csc=None,
            csc_id=None,
            created_at=_now(),
            updated_at=_now(),
        )

        with session_scope(session_factory) as session:
            emitter_repository = SqlAlchemyEmitterRepository(session)
            document_repository = SqlAlchemyDocumentRepository(session)
            job_repository = SqlAlchemyJobRepository(session)
            emitter_repository.save(emitter)

            service = DocumentService(
                document_repository=document_repository,
                emitter_repository=emitter_repository,
                job_service=JobService(job_repository),
                queue=queue,
                database_url=database_url,
                encryption_key="dummy-key",
            )
            _document, job, replayed = service.create_document(
                emitter_id=emitter.id,
                external_id="erp-doc-auto-queue",
                idempotency_key="idem-auto-queue",
                document_type="factura",
                payload_snapshot={"total": "100000"},
            )

        assert replayed is False
        assert queue.job_ids == [job.id]


class _FakeDocumentQueue:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    def enqueue_document_emit(self, job, *, database_url: str, encryption_key: str):
        assert database_url
        assert encryption_key
        self.job_ids.append(job.id)
        return {"job_id": job.id}


class _FixedNumberingService:
    def __init__(self) -> None:
        self.calls = 0

    def reserve_next_number(self, **_kwargs) -> int:
        self.calls += 1
        return 42


def _emitter() -> Emitter:
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
        created_at=_now(),
        updated_at=_now(),
    )


def _now() -> datetime:
    return datetime.now(UTC)
