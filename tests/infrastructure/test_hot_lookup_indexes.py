"""Hot lookups are indexed, and listing documents reads their jobs at once."""

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import event, inspect
from sqlalchemy.engine.url import make_url

from alembic import command
from kilasifen.domain.jobs.models import Job
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.models import (
    ApiKeyModel,
    DocumentModel,
    EventModel,
    JobModel,
)
from kilasifen.infrastructure.db.repositories.jobs import SqlAlchemyJobRepository
from kilasifen.infrastructure.db.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from kilasifen.testing.database import managed_test_database_url

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INDEXED_MODELS = (ApiKeyModel, DocumentModel, EventModel, JobModel)


def _declared_indexes() -> dict[str, set[str]]:
    return {
        model.__tablename__: {index.name for index in model.__table__.indexes}
        for model in _INDEXED_MODELS
    }


def test_migrations_create_the_indexes_the_models_declare(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with managed_test_database_url(tmp_path=tmp_path, name="hot_indexes") as url:
        config = Config(str(_REPO_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", url)

        command.upgrade(config, "head")

        options = str(make_url(url).query.get("options", "")).strip()
        schema = (
            options.split("search_path=")[-1].split()[0]
            if "search_path=" in options
            else None
        )
        inspector = inspect(build_engine(url))
        for table, declared in _declared_indexes().items():
            migrated = {
                index["name"] for index in inspector.get_indexes(table, schema=schema)
            }
            assert declared <= migrated, (table, sorted(declared - migrated))


def test_the_hot_lookups_are_declared() -> None:
    declared = _declared_indexes()

    assert "ix_jobs_related_entity" in declared["jobs"]
    assert "ix_jobs_emitter_created" in declared["jobs"]
    assert "ix_api_keys_key_prefix" in declared["api_keys"]
    assert {"ix_documents_emitter_created", "ix_documents_emitter_cdc"} <= declared[
        "documents"
    ]
    assert "ix_events_document_created" in declared["events"]


@pytest.fixture
def session_factory(tmp_path: Path) -> Iterator:
    with managed_test_database_url(tmp_path=tmp_path, name="latest_jobs") as url:
        engine = build_engine(url)
        Base.metadata.create_all(engine)
        yield build_session_factory(engine)


def _job(job_id: str, entity_id: str, created_at: datetime) -> Job:
    return Job(
        id=job_id,
        emitter_id=None,
        related_entity_type="document",
        related_entity_id=entity_id,
        job_type="document.emit",
        status="queued",
        attempts=0,
        error_snapshot=None,
        scheduled_at=created_at,
        started_at=None,
        finished_at=None,
        worker_correlation_id=None,
        created_at=created_at,
        updated_at=created_at,
    )


def test_latest_for_entities_returns_each_entity_its_newest_job(
    session_factory,
) -> None:
    start = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    with session_scope(session_factory) as session:
        repository = SqlAlchemyJobRepository(session)
        repository.save(_job("old", "doc-a", start))
        repository.save(_job("new", "doc-a", start + timedelta(minutes=5)))
        repository.save(_job("only", "doc-b", start))

    with session_scope(session_factory) as session:
        latest = SqlAlchemyJobRepository(session).latest_for_entities(
            "document", ["doc-a", "doc-b", "doc-without-job"]
        )

    assert {entity: job.id for entity, job in latest.items()} == {
        "doc-a": "new",
        "doc-b": "only",
    }


def test_latest_for_entities_reads_every_job_in_one_query(session_factory) -> None:
    start = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    entity_ids = [f"doc-{number}" for number in range(25)]
    with session_scope(session_factory) as session:
        repository = SqlAlchemyJobRepository(session)
        for number, entity_id in enumerate(entity_ids):
            repository.save(_job(f"job-{number}", entity_id, start))

    statements: list[str] = []
    engine = session_factory.kw["bind"]

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with session_scope(session_factory) as session:
            latest = SqlAlchemyJobRepository(session).latest_for_entities(
                "document", entity_ids
            )
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert len(latest) == len(entity_ids)
    assert len([s for s in statements if "FROM jobs" in s]) == 1
