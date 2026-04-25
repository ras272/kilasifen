from datetime import UTC, datetime

import fakeredis
from rq import Queue

from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.jobs.models import Job
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.repositories.documents import SqlAlchemyDocumentRepository
from kilasifen.infrastructure.db.repositories.emitters import SqlAlchemyEmitterRepository
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.session import build_engine, build_session_factory, session_scope
from kilasifen.infrastructure.jobs.queue import RqJobQueue
from kilasifen.infrastructure.jobs.workers import process_document_job


def test_rq_queue_enqueues_document_job_with_expected_payload() -> None:
    queue = Queue("documents", connection=fakeredis.FakeRedis())
    adapter = RqJobQueue(queue)

    job = Job(
        id="job-1",
        emitter_id="emitter-1",
        related_entity_type="document",
        related_entity_id="document-1",
        job_type="document.emit",
        status="queued",
        attempts=0,
        error_snapshot=None,
        scheduled_at=_now(),
        started_at=None,
        finished_at=None,
        worker_correlation_id=None,
        created_at=_now(),
        updated_at=_now(),
    )

    enqueued = adapter.enqueue_document_emit(job)

    assert enqueued.func_name == "kilasifen.infrastructure.jobs.workers.process_document_job"
    assert enqueued.kwargs["job_id"] == "job-1"


def test_process_document_job_hydrates_job_and_document_context(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'worker.db'}"
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
    document = Document(
        id="document-1",
        emitter_id="emitter-1",
        external_id="erp-doc-1",
        idempotency_key="idem-1",
        document_type="factura",
        payload_snapshot={"total": "100000"},
        generated_xml=None,
        signed_xml=None,
        cdc=None,
        internal_status="queued",
        sifen_status=None,
        sifen_result_code=None,
        sifen_result_message=None,
        created_at=_now(),
        updated_at=_now(),
    )
    job = Job(
        id="job-1",
        emitter_id="emitter-1",
        related_entity_type="document",
        related_entity_id="document-1",
        job_type="document.emit",
        status="queued",
        attempts=0,
        error_snapshot=None,
        scheduled_at=_now(),
        started_at=None,
        finished_at=None,
        worker_correlation_id=None,
        created_at=_now(),
        updated_at=_now(),
    )

    with session_scope(session_factory) as session:
        SqlAlchemyEmitterRepository(session).save(emitter)
        SqlAlchemyDocumentRepository(session).save(document)
        SqlAlchemyJobRepository(session).save(job)

    payload = process_document_job(job_id="job-1", database_url=database_url)

    assert payload["job_id"] == "job-1"
    assert payload["document_id"] == "document-1"
    assert payload["document_type"] == "factura"
    assert payload["job_type"] == "document.emit"


def _now() -> datetime:
    return datetime.now(UTC)
