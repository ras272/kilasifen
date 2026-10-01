from pathlib import Path

from alembic.config import Config
from sqlalchemy import text

from alembic import command
from kilasifen.infrastructure.db.repositories.emitters import (
    SqlAlchemyEmitterRepository,
)
from kilasifen.infrastructure.db.session import (
    build_engine,
    build_session_factory,
    session_scope,
)
from kilasifen.testing.database import managed_test_database_url


def test_existing_emitters_get_an_empty_fiscal_profile(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    with managed_test_database_url(
        tmp_path=tmp_path, name="emitter_fiscal_profile_upgrade"
    ) as url:
        config = Config(str(repo_root / "alembic.ini"))
        config.set_main_option("script_location", str(repo_root / "alembic"))
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", url)
        command.upgrade(config, "20260822_08")

        engine = build_engine(url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO emitters
                        (id, external_id, ruc, dv, legal_name, tax_environment,
                         status)
                    VALUES
                        ('legacy-emitter', 'legacy-erp', '44444401', '7',
                         'Legacy Emitter', 'test', 'active')
                    """
                )
            )

        command.upgrade(config, "20261001_09")

        with session_scope(build_session_factory(engine)) as session:
            summary = SqlAlchemyEmitterRepository(session).get_summary(
                "legacy-emitter"
            )

        assert summary is not None
        assert summary.fiscal_profile is None
