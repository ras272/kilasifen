from pathlib import Path

from alembic import command
from alembic.config import Config
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.models import (
    ApiKeyModel,
    CertificateModel,
    DocumentModel,
    EmitterModel,
    EventModel,
    JobModel,
    StampingModel,
    WebhookDeliveryModel,
    WebhookEndpointModel,
)
from kilasifen.infrastructure.db.session import build_engine, build_session_factory
from sqlalchemy import inspect, text

EXPECTED_TABLES = {
    ApiKeyModel.__tablename__,
    CertificateModel.__tablename__,
    DocumentModel.__tablename__,
    EmitterModel.__tablename__,
    EventModel.__tablename__,
    JobModel.__tablename__,
    StampingModel.__tablename__,
    WebhookDeliveryModel.__tablename__,
    WebhookEndpointModel.__tablename__,
}


def test_metadata_registers_core_tables() -> None:
    assert EXPECTED_TABLES.issubset(set(Base.metadata.tables))


def test_build_session_factory_returns_working_session(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'session.db'}"
    engine = build_engine(database_url)
    session_factory = build_session_factory(engine)

    with session_factory() as session:
        assert session.execute(text("SELECT 1")).scalar_one() == 1


def test_alembic_upgrade_creates_core_tables(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    database_url = f"sqlite:///{tmp_path / 'migration.db'}"
    alembic_config = Config(str(repo_root / "alembic.ini"))
    alembic_config.set_main_option("script_location", str(repo_root / "alembic"))
    alembic_config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(alembic_config, "head")

    inspector = inspect(build_engine(database_url))
    assert EXPECTED_TABLES.issubset(set(inspector.get_table_names()))
