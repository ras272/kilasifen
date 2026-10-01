from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import fakeredis
import pytest
from rq import Queue
from rq.job import Job as RqJob
from rq.job import JobStatus

from kilasifen.application.jobs.service import JobService
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.repositories.job_outbox import (
    SqlAlchemyJobOutboxRepository,
)
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.session import build_engine, build_session_factory
from kilasifen.infrastructure.jobs.outbox import (
    JobOutboxDispatcher,
    PublicationDeferredError,
    SqlAlchemyJobOutboxQueue,
)
from kilasifen.infrastructure.jobs.queue import RqJobQueue


def test_outbox_never_publishes_before_business_commit(tmp_path) -> None:
    session_factory = _session_factory(tmp_path, "before_commit")
    published: list[str] = []
    dispatcher = JobOutboxDispatcher(
        session_factory=session_factory,
        queues={"documents": _RecordingQueue(published)},
    )

    session = session_factory()
    job = JobService(SqlAlchemyJobRepository(session)).create_job(
        emitter_id=None,
        related_entity_type="document",
        related_entity_id="document-1",
        job_type="document.emit",
    )
    SqlAlchemyJobOutboxQueue(
        SqlAlchemyJobOutboxRepository(session)
    ).enqueue_document_emit(job)

    assert dispatcher.dispatch_once() == 0
    assert published == []

    session.commit()
    session.close()
    assert dispatcher.dispatch_once() == 1
    assert published == [job.id]


def test_outbox_recovers_after_redis_failure_without_leaking_error(tmp_path) -> None:
    session_factory = _session_factory(tmp_path, "redis_recovery")
    clock = _MutableClock(datetime.now(timezone.utc) + timedelta(seconds=1))
    queue = _FailOnceQueue()
    job_id = _stage_document_job(session_factory)
    dispatcher = JobOutboxDispatcher(
        session_factory=session_factory,
        queues={"documents": queue},
        retry_delays=(5,),
        clock=clock,
    )

    assert dispatcher.dispatch_once() == 0
    with session_factory() as session:
        failed = SqlAlchemyJobOutboxRepository(session).get_for_job(job_id)
        assert failed is not None
        assert failed.status == "pending"
        assert failed.attempts == 1
        assert failed.last_error == "ConnectionError: queue publication failed"
        assert "redis://" not in failed.last_error

    clock.now += timedelta(seconds=5)
    assert dispatcher.dispatch_once() == 1
    with session_factory() as session:
        published = SqlAlchemyJobOutboxRepository(session).get_for_job(job_id)
        assert published is not None
        assert published.status == "published"
        assert published.attempts == 2
        assert published.last_error is None
    assert queue.published == [job_id]


@pytest.mark.parametrize(
    ("method_name", "job_type", "queue_name"),
    [
        ("enqueue_document_emit", "document.emit", "documents"),
        ("enqueue_event_submit", "event.submit", "events"),
        ("enqueue_webhook_delivery", "webhook.deliver", "webhooks"),
    ],
)
def test_all_job_queue_ports_stage_the_expected_outbox_route(
    tmp_path,
    method_name: str,
    job_type: str,
    queue_name: str,
) -> None:
    session_factory = _session_factory(tmp_path, job_type.replace(".", "_"))
    with session_factory() as session, session.begin():
        job = JobService(SqlAlchemyJobRepository(session)).create_job(
            emitter_id=None,
            related_entity_type="test",
            related_entity_id="entity-1",
            job_type=job_type,
        )
        queue = SqlAlchemyJobOutboxQueue(SqlAlchemyJobOutboxRepository(session))
        getattr(queue, method_name)(job)

    with session_factory() as session:
        message = SqlAlchemyJobOutboxRepository(session).get_for_job(job.id)
        assert message is not None
        assert message.queue_name == queue_name
        assert message.status == "pending"


def test_active_lease_prevents_a_second_dispatcher_from_claiming(tmp_path) -> None:
    session_factory = _session_factory(tmp_path, "replica_lease")
    _stage_document_job(session_factory)
    now = datetime.now(timezone.utc) + timedelta(seconds=1)
    first = JobOutboxDispatcher(
        session_factory=session_factory,
        queues={},
        worker_id="dispatcher-1",
        clock=lambda: now,
    )
    second = JobOutboxDispatcher(
        session_factory=session_factory,
        queues={},
        worker_id="dispatcher-2",
        clock=lambda: now,
    )

    claimed = first._claim(limit=1)

    assert len(claimed) == 1
    assert second._claim(limit=1) == []


def test_retry_is_invisible_before_commit_and_dispatches_after_due_time(
    tmp_path,
) -> None:
    session_factory = _session_factory(tmp_path, "retry_commit")
    published: list[str] = []
    initial_clock = datetime.now(timezone.utc) + timedelta(seconds=1)
    dispatcher = JobOutboxDispatcher(
        session_factory=session_factory,
        queues={"documents": _RecordingQueue(published)},
        clock=lambda: initial_clock,
    )
    job_id = _stage_document_job(session_factory)
    assert dispatcher.dispatch_once() == 1

    retry_at = initial_clock + timedelta(seconds=30)
    session = session_factory()
    _stage_document_retry(session, job_id=job_id, retry_at=retry_at)

    dispatcher.clock = lambda: retry_at
    assert dispatcher.dispatch_once() == 0
    session.rollback()
    session.close()
    assert dispatcher.dispatch_once() == 0

    with session_factory() as session, session.begin():
        _stage_document_retry(session, job_id=job_id, retry_at=retry_at)

    dispatcher.clock = lambda: retry_at - timedelta(microseconds=1)
    assert dispatcher.dispatch_once() == 0
    dispatcher.clock = lambda: retry_at
    assert dispatcher.dispatch_once() == 1
    assert published == [job_id, job_id]


def test_retry_restaging_revokes_an_unconfirmed_publication_lease(tmp_path) -> None:
    session_factory = _session_factory(tmp_path, "retry_publication_race")
    job_id = _stage_document_job(session_factory)
    now = datetime.now(timezone.utc) + timedelta(seconds=1)
    dispatcher = JobOutboxDispatcher(
        session_factory=session_factory,
        queues={},
        worker_id="original-dispatcher",
        clock=lambda: now,
    )
    [claimed] = dispatcher._claim(limit=1)

    retry_at = now + timedelta(seconds=30)
    with session_factory() as session, session.begin():
        _stage_document_retry(session, job_id=job_id, retry_at=retry_at)

    with session_factory() as session, session.begin():
        confirmed = SqlAlchemyJobOutboxRepository(session).mark_published(
            message_id=claimed.id,
            worker_id="original-dispatcher",
            published_at=now,
        )
        message = SqlAlchemyJobOutboxRepository(session).get_for_job(job_id)

    assert confirmed is False
    assert message is not None
    assert message.status == "pending"
    assert message.available_at.replace(tzinfo=timezone.utc) == retry_at


def test_rq_publication_is_idempotent_by_job_id() -> None:
    redis_connection = fakeredis.FakeRedis()
    queue = Queue("documents", connection=redis_connection)
    adapter = RqJobQueue(queue)

    first = adapter.enqueue_outbox_job(
        job_id="job-1",
        job_type="document.emit",
        correlation_id="request-1",
    )
    second = adapter.enqueue_outbox_job(
        job_id="job-1",
        job_type="document.emit",
        correlation_id="request-1",
    )

    assert first is not None
    assert second is not None
    assert first.id == second.id == "job-1"
    assert queue.job_ids == ["job-1"]


def test_a_started_rq_record_defers_publication_until_it_ends() -> None:
    queue = Queue("documents", connection=fakeredis.FakeRedis())
    adapter = RqJobQueue(queue)
    running = adapter.enqueue_outbox_job(
        job_id="job-1",
        job_type="document.emit",
        correlation_id=None,
    )
    running.set_status(JobStatus.STARTED)

    with pytest.raises(PublicationDeferredError):
        adapter.enqueue_outbox_job(
            job_id="job-1",
            job_type="document.emit",
            correlation_id=None,
        )

    running.set_status(JobStatus.FAILED)
    again = adapter.enqueue_outbox_job(
        job_id="job-1",
        job_type="document.emit",
        correlation_id=None,
    )
    assert again.get_status(refresh=True) == JobStatus.QUEUED
    assert queue.job_ids == ["job-1"]


def test_an_operator_retry_survives_a_run_rq_still_reports_started(
    tmp_path,
) -> None:
    session_factory = _session_factory(tmp_path, "started_rq_run")
    clock = _MutableClock(datetime.now(timezone.utc) + timedelta(seconds=1))
    job_id = _stage_document_job(session_factory)
    queue = Queue("documents", connection=fakeredis.FakeRedis())
    dispatcher = JobOutboxDispatcher(
        session_factory=session_factory,
        queues={"documents": RqJobQueue(queue)},
        retry_delays=(5,),
        clock=clock,
    )
    assert dispatcher.dispatch_once() == 1
    # Its worker died mid-run: RQ keeps the record started until cleanup.
    RqJob.fetch(job_id, connection=queue.connection).set_status(JobStatus.STARTED)

    with session_factory() as session, session.begin():
        job = SqlAlchemyJobRepository(session).get(job_id)
        SqlAlchemyJobOutboxQueue(
            SqlAlchemyJobOutboxRepository(session)
        ).enqueue_document_emit(job)

    assert dispatcher.dispatch_once() == 0
    with session_factory() as session:
        deferred = SqlAlchemyJobOutboxRepository(session).get_for_job(job_id)
    assert deferred is not None and deferred.status == "pending"
    assert deferred.last_error == (
        "PublicationDeferredError: job still running in queue"
    )

    RqJob.fetch(job_id, connection=queue.connection).set_status(JobStatus.FAILED)
    clock.now += timedelta(seconds=5)

    assert dispatcher.dispatch_once() == 1
    republished = RqJob.fetch(job_id, connection=queue.connection)
    assert republished.get_status(refresh=True) == JobStatus.QUEUED


def test_expired_lease_recovery_does_not_duplicate_rq_publication(tmp_path) -> None:
    session_factory = _session_factory(tmp_path, "crash_recovery")
    job_id = _stage_document_job(session_factory)
    redis_connection = fakeredis.FakeRedis()
    queue = Queue("documents", connection=redis_connection)
    adapter = RqJobQueue(queue)
    now = datetime.now(timezone.utc) + timedelta(seconds=1)
    crashed_dispatcher = JobOutboxDispatcher(
        session_factory=session_factory,
        queues={"documents": adapter},
        worker_id="crashed-dispatcher",
        lease_seconds=5,
        clock=lambda: now,
    )
    [claimed] = crashed_dispatcher._claim(limit=1)
    adapter.enqueue_outbox_job(
        job_id=claimed.job_id,
        job_type="document.emit",
        correlation_id=claimed.correlation_id,
    )

    recovered_dispatcher = JobOutboxDispatcher(
        session_factory=session_factory,
        queues={"documents": adapter},
        worker_id="recovered-dispatcher",
        clock=lambda: now + timedelta(seconds=5),
    )

    assert recovered_dispatcher.dispatch_once() == 1
    assert queue.job_ids == [job_id]


def _session_factory(tmp_path, name: str):
    database_url = f"sqlite:///{tmp_path / f'{name}.db'}"
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def _stage_document_job(session_factory) -> str:
    with session_factory() as session, session.begin():
        job = JobService(SqlAlchemyJobRepository(session)).create_job(
            emitter_id=None,
            related_entity_type="document",
            related_entity_id="document-1",
            job_type="document.emit",
        )
        SqlAlchemyJobOutboxQueue(
            SqlAlchemyJobOutboxRepository(session)
        ).enqueue_document_emit(job)
        return job.id


def _stage_document_retry(session, *, job_id: str, retry_at: datetime) -> None:
    jobs = SqlAlchemyJobRepository(session)
    job = jobs.get(job_id)
    assert job is not None
    retry_job = jobs.save(
        replace(job, status="retry_scheduled", scheduled_at=retry_at)
    )
    SqlAlchemyJobOutboxQueue(
        SqlAlchemyJobOutboxRepository(session)
    ).enqueue_document_emit(retry_job)


class _RecordingQueue:
    def __init__(self, published: list[str]):
        self.published = published

    def enqueue_outbox_job(self, *, job_id: str, **_kwargs):
        self.published.append(job_id)


class _FailOnceQueue(_RecordingQueue):
    def __init__(self):
        super().__init__([])
        self.failed = False

    def enqueue_outbox_job(self, *, job_id: str, **kwargs):
        if not self.failed:
            self.failed = True
            raise ConnectionError("redis://:super-secret@redis.internal")
        super().enqueue_outbox_job(job_id=job_id, **kwargs)


class _MutableClock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now
