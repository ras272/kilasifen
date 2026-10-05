from pathlib import Path

from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine.url import make_url

from alembic import command
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.models import (
    ApiKeyModel,
    CertificateModel,
    ConsumerEmitterModel,
    ConsumerModel,
    DocumentModel,
    DocumentNumberingSequenceModel,
    EmitterModel,
    EventModel,
    InutilizedNumberRangeModel,
    JobModel,
    JobOutboxModel,
    StampingModel,
    WebhookDeliveryModel,
    WebhookEndpointModel,
)
from kilasifen.infrastructure.db.session import build_engine, build_session_factory
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
    JobOutboxModel.__tablename__,
    StampingModel.__tablename__,
    WebhookDeliveryModel.__tablename__,
    WebhookEndpointModel.__tablename__,
}


def test_metadata_registers_core_tables() -> None:
    assert EXPECTED_TABLES.issubset(set(Base.metadata.tables))


def test_build_session_factory_returns_working_session(tmp_path: Path) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path, name="db_foundation_session"
    ) as database_url:
        engine = build_engine(database_url)
        session_factory = build_session_factory(engine)

        with session_factory() as session:
            assert session.execute(text("SELECT 1")).scalar_one() == 1


def test_alembic_upgrade_creates_core_tables(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    with managed_test_database_url(
        tmp_path=tmp_path, name="db_foundation_migration"
    ) as database_url:
        alembic_config = Config(str(repo_root / "alembic.ini"))
        alembic_config.set_main_option("script_location", str(repo_root / "alembic"))
        alembic_config.set_main_option(
            "sqlalchemy.url", database_url.replace("%", "%%")
        )
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)

        command.upgrade(alembic_config, "head")

        parsed_url = make_url(database_url)
        options = str(parsed_url.query.get("options", "")).strip()
        schema = None
        if "search_path=" in options:
            schema = options.split("search_path=")[-1].split()[0]
        inspector = inspect(build_engine(database_url))
        assert EXPECTED_TABLES.issubset(set(inspector.get_table_names(schema=schema)))

        # Every column the ORM maps on ``documents`` exists after migrating,
        # including the SIFEN outcome fields of revision 20261001_15.
        migrated = {
            column["name"]
            for column in inspector.get_columns(
                DocumentModel.__tablename__, schema=schema
            )
        }
        assert set(DocumentModel.__table__.columns.keys()) <= migrated
        assert {
            "sifen_approved_at",
            "sifen_protocol",
            "sifen_messages",
            "retryable_server_error",
            "timbrado",
        } <= migrated


def test_the_outcome_migration_reads_the_timbrado_of_legacy_documents(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Revision 20261001_15 fills ``timbrado`` from ``dNumTim`` (C004).

    A number is inutilized per timbrado (1109, MT v150 §12.4 C007 p. 161):
    a document signed before the column existed must not count for every
    timbrado. Only a document never built keeps NULL.
    """

    repo_root = Path(__file__).resolve().parents[2]
    with managed_test_database_url(
        tmp_path=tmp_path, name="db_timbrado_backfill"
    ) as database_url:
        alembic_config = Config(str(repo_root / "alembic.ini"))
        alembic_config.set_main_option("script_location", str(repo_root / "alembic"))
        alembic_config.set_main_option(
            "sqlalchemy.url", database_url.replace("%", "%%")
        )
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", database_url)
        command.upgrade(alembic_config, "20260822_08")

        engine = build_engine(database_url)
        signed = (
            '<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd"><DE><gTimb>'
            "<iTiDE>1</iTiDE><dNumTim>12345678</dNumTim></gTimb></DE></rDE>"
        )
        generated = "<rDE><DE><gTimb><dNumTim>87654321</dNumTim></gTimb></DE></rDE>"
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO emitters (id, ruc, dv, legal_name, "
                    "tax_environment, status) VALUES ('emitter-1', '80000001', "
                    "'7', 'EMISOR DE PRUEBA SA', 'test', 'active')"
                )
            )
            for document_id, generated_xml, signed_xml in (
                ("doc-signed", generated, signed),
                ("doc-generated", generated, None),
                ("doc-never-built", None, None),
            ):
                connection.execute(
                    text(
                        "INSERT INTO documents (id, emitter_id, document_type, "
                        "internal_status, generated_xml, signed_xml) VALUES "
                        "(:id, 'emitter-1', 'factura', 'rejected', :generated, "
                        ":signed)"
                    ),
                    {
                        "id": document_id,
                        "generated": generated_xml,
                        "signed": signed_xml,
                    },
                )
        engine.dispose()

        command.upgrade(alembic_config, "head")

        engine = build_engine(database_url)
        with engine.connect() as connection:
            timbrados = dict(
                connection.execute(text("SELECT id, timbrado FROM documents")).all()
            )
        engine.dispose()
        assert timbrados == {
            "doc-signed": "12345678",
            "doc-generated": "87654321",
            "doc-never-built": None,
        }
