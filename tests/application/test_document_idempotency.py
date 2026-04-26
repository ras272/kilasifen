from datetime import UTC, datetime

from kilasifen.application.documents.service import DocumentService
from kilasifen.application.jobs.service import JobService
from kilasifen.domain.emitters.models import Emitter
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.repositories.documents import SqlAlchemyDocumentRepository
from kilasifen.infrastructure.db.repositories.emitters import SqlAlchemyEmitterRepository
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.session import build_engine, build_session_factory, session_scope
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
                payload_snapshot={"total": "100000"},
            )
            second_document, second_job, second_replayed = service.create_document(
                emitter_id=emitter.id,
                external_id="erp-doc-1",
                idempotency_key="idem-1",
                document_type="factura",
                payload_snapshot={"total": "100000"},
            )

        assert second_document.id == first_document.id
        assert second_job.id == first_job.id
        assert first_replayed is False
        assert second_replayed is True


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


def _now() -> datetime:
    return datetime.now(UTC)
