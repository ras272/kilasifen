from pathlib import Path

from alembic import command
from alembic.config import Config
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.models import (
    ApiKeyModel,
    CertificateModel,
    ConsumerEmitterModel,
    ConsumerModel,
    DocumentNumberingSequenceModel,
    DocumentModel,
    EmitterModel,
    EventModel,
    InutilizedNumberRangeModel,
    JobModel,
    StampingModel,
    WebhookDeliveryModel,
    WebhookEndpointModel,
)
from kilasifen.infrastructure.db.session import build_engine, build_session_factory
from sqlalchemy import inspect, text
from sqlalchemy.engine.url import make_url
from kilasifen.testing.database import managed_test_database_url

EXPECTED_TABLES = {
    ApiKeyModel.__tablename__,
    CertificateModel.__tablename__,
    ConsumerModel.__tablename__,
    ConsumerEmitterModel.__tablename__,
    DocumentModel.__tablename__,
    DocumentNumberingSequenceModel.__tablename__,
    EmitterModel.__tablename__,
    EventModel.__tablename__,
    InutilizedNumberRangeModel.__tablename__,
    JobModel.__tablename__,
    StampingModel.__tablename__,
    WebhookDeliveryModel.__tablename__,
    WebhookEndpointModel.__tablename__,
}


def test_metadata_registers_core_tables() -> None:
    assert EXPECTED_TABLES.issubset(set(Base.metadata.tables))


def test_build_session_factory_returns_working_session(tmp_path: Path) -> None:
    with managed_test_database_url(tmp_path=tmp_path, name="db_foundation_session") as database_url:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)

        with session_factory() as session:
            assert session.execute(text("SELECT 1")).scalar_one() == 1


def test_alembic_upgrade_creates_core_tables(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    with managed_test_database_url(tmp_path=tmp_path, name="db_foundation_migration") as database_url:
        alembic_config = Config(str(repo_root / "alembic.ini"))
        alembic_config.set_main_option("script_location", str(repo_root / "alembic"))
        alembic_config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)

        command.upgrade(alembic_config, "head")

        parsed_url = make_url(database_url)
        options = str(parsed_url.query.get("options", "")).strip()
        schema = None
        if "search_path=" in options:
            schema = options.split("search_path=")[-1].split()[0]
        inspector = inspect(build_engine(database_url))
        assert EXPECTED_TABLES.issubset(set(inspector.get_table_names(schema=schema)))
