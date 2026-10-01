"""Bounded row-lock waits and locked fresh reads."""

import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from kilasifen.application.emitters.guards import (
    require_active_emitter,
    require_active_emitter_without_lock,
)
from kilasifen.domain.common.errors import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
)
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.jobs.models import Job
from kilasifen.infrastructure.db import locks
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.models import JobModel
from kilasifen.infrastructure.db.repositories import emitters as emitter_repositories
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


class _PgError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class _FakePostgresSession:
    """Records statements the way a PostgreSQL session would receive them."""

    def __init__(self, *, previous_timeout: str = "0") -> None:
        self.previous_timeout = previous_timeout
        self.statements: list[tuple[str, dict | None]] = []

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def scalar(self, statement, params=None):
        self.statements.append((str(statement), params))
        return self.previous_timeout

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))


def _lock_timeout_error(sqlstate: str = "55P03") -> OperationalError:
    return OperationalError("SELECT ... FOR UPDATE", {}, _PgError(sqlstate))


def test_lock_timeout_is_bounded_and_restored_on_postgresql() -> None:
    session = _FakePostgresSession(previous_timeout="2s")

    result = locks.run_with_lock_timeout(
        session,
        lambda: "locked",
        timeout_ms=750,
        error_code="emitters.lock_timeout",
    )

    assert result == "locked"
    assert session.statements == [
        ("SELECT current_setting('lock_timeout')", None),
        ("SELECT set_config('lock_timeout', :value, true)", {"value": "750ms"}),
        ("SELECT set_config('lock_timeout', :value, true)", {"value": "2s"}),
    ]


@pytest.mark.parametrize("sqlstate", ["55P03", "57014"])
def test_lock_timeout_becomes_a_retryable_service_error(sqlstate: str) -> None:
    session = _FakePostgresSession()

    def blocked():
        raise _lock_timeout_error(sqlstate)

    with pytest.raises(ServiceUnavailableError, match="emitters.lock_timeout"):
        locks.run_with_lock_timeout(
            session,
            blocked,
            timeout_ms=100,
            error_code="emitters.lock_timeout",
        )


def test_other_database_errors_are_not_disguised_as_lock_timeouts() -> None:
    session = _FakePostgresSession()
    error = _lock_timeout_error("40P01")

    def deadlocked():
        raise error

    with pytest.raises(OperationalError) as raised:
        locks.run_with_lock_timeout(
            session,
            deadlocked,
            timeout_ms=100,
            error_code="emitters.lock_timeout",
        )
    assert raised.value is error


def test_lock_timeout_is_a_no_op_outside_postgresql(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'locks.db'}")
    with build_session_factory(engine)() as session:
        assert (
            locks.run_with_lock_timeout(
                session,
                lambda: 42,
                timeout_ms=100,
                error_code="emitters.lock_timeout",
            )
            == 42
        )


def test_emitter_lock_reports_its_own_timeout_code() -> None:
    session = _FakePostgresSession()

    def blocked(statement, params=None):
        if "FOR UPDATE" in str(statement):
            raise _lock_timeout_error()
        return "0"

    session.scalar = blocked
    repository = SqlAlchemyEmitterRepository(session)

    with pytest.raises(ServiceUnavailableError, match="emitters.lock_timeout"):
        require_active_emitter(repository, "emitter-1")


def test_unlocked_guard_checks_status_without_select_for_update(
    tmp_path: Path,
) -> None:
    session_factory = _sqlite_session_factory(tmp_path)
    _seed_emitter(session_factory, status="active")
    _seed_emitter(
        session_factory, emitter_id="emitter-2", ruc="80000001", status="inactive"
    )

    with session_scope(session_factory) as session:
        repository = SqlAlchemyEmitterRepository(session)
        repository.get_status_for_update = _fail_if_called
        require_active_emitter_without_lock(repository, "emitter-1")
        with pytest.raises(ConflictError, match="emitters.inactive"):
            require_active_emitter_without_lock(repository, "emitter-2")
        with pytest.raises(NotFoundError, match="emitters.not_found"):
            require_active_emitter_without_lock(repository, "missing")


def test_get_for_update_reloads_rows_changed_by_other_transactions(
    tmp_path: Path,
) -> None:
    session_factory = _sqlite_session_factory(tmp_path)
    _seed_emitter(session_factory, status="active")
    with session_scope(session_factory) as session:
        SqlAlchemyJobRepository(session).save(_job())

    with session_scope(session_factory) as reader:
        jobs = SqlAlchemyJobRepository(reader)
        cached_model = reader.get(JobModel, "job-1")  # pins the identity map copy
        stale = jobs.get("job-1")
        assert stale is not None and stale.attempts == 0

        with session_scope(session_factory) as writer:
            SqlAlchemyJobRepository(writer).save(replace(stale, attempts=3))

        assert jobs.get("job-1").attempts == 0
        fresh = jobs.get_for_update("job-1")
        assert fresh is not None and fresh.attempts == 3
        assert cached_model.attempts == 3
        assert jobs.get_for_update("missing") is None


@pytest.fixture
def postgres_database_url(tmp_path: Path) -> Iterator[str]:
    if not os.getenv("KILA_SIFEN_TEST_DATABASE_URL"):
        pytest.skip("KILA_SIFEN_TEST_DATABASE_URL is required for row-lock tests.")
    with managed_test_database_url(tmp_path=tmp_path, name="row_locks") as url:
        yield url


@pytest.mark.requires_postgres
def test_emitter_lock_wait_is_bounded_on_postgresql(
    postgres_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(emitter_repositories, "EMITTER_LOCK_TIMEOUT_MS", 200)
    engine = build_engine(postgres_database_url)
    Base.metadata.create_all(engine)
    session_factory = build_session_factory(engine)
    _seed_emitter(session_factory, status="active")

    holder = session_factory()
    try:
        require_active_emitter(SqlAlchemyEmitterRepository(holder), "emitter-1")
        assert holder.scalar(text("SHOW lock_timeout")) == "0"

        waiter = session_factory()
        try:
            started = datetime.now(timezone.utc)
            with pytest.raises(ServiceUnavailableError, match="lock_timeout"):
                require_active_emitter(SqlAlchemyEmitterRepository(waiter), "emitter-1")
            waited = datetime.now(timezone.utc) - started
            assert waited.total_seconds() < 5
        finally:
            waiter.rollback()
            waiter.close()
    finally:
        holder.rollback()
        holder.close()
        engine.dispose()


def _fail_if_called(emitter_id: str) -> str | None:
    raise AssertionError(f"emitter {emitter_id} must not be locked")


def _sqlite_session_factory(tmp_path: Path):
    engine = build_engine(f"sqlite:///{tmp_path / 'locks.db'}")
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def _seed_emitter(
    session_factory,
    *,
    status: str,
    emitter_id: str = "emitter-1",
    ruc: str = "80024135",
) -> None:
    with session_scope(session_factory) as session:
        SqlAlchemyEmitterRepository(session).save(
            Emitter(
                id=emitter_id,
                external_id=f"erp-{emitter_id}",
                ruc=ruc,
                dv="5",
                legal_name="EMISOR FICTICIO SA",
                tax_environment="test",
                status=status,
                csc=None,
                csc_id=None,
                created_at=_now(),
                updated_at=_now(),
            )
        )


def _job() -> Job:
    return Job(
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


def _now() -> datetime:
    return datetime.now(timezone.utc)
