from pathlib import Path

from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from sqlalchemy import text

from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.session import build_engine
from kilasifen.testing.database import managed_test_database_url


def test_upgrade_backfills_ownership_and_encrypts_existing_csc(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    with managed_test_database_url(tmp_path=tmp_path, name="tenancy_secret_upgrade") as url:
        config = Config(str(repo_root / "alembic.ini"))
        config.set_main_option("script_location", str(repo_root / "alembic"))
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", url)
        command.upgrade(config, "20260426_05")

        engine = build_engine(url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO emitters
                        (id, external_id, ruc, dv, legal_name, tax_environment, status, csc)
                    VALUES
                        ('legacy-emitter', 'legacy-erp', '80000001', '1',
                         'Legacy Emitter', 'test', 'active', 'legacy-csc-secret')
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO api_keys
                        (id, emitter_id, name, key_prefix, key_hash, status)
                    VALUES
                        ('legacy-key', 'legacy-emitter', 'Legacy key', 'legacy',
                         'legacy-one-way-hash', 'active')
                    """
                )
            )

        encryption_key = Fernet.generate_key().decode("ascii")
        monkeypatch.setenv("KILA_SIFEN_ENCRYPTION_KEY", encryption_key)
        command.upgrade(config, "head")

        with engine.connect() as connection:
            encrypted_csc = connection.execute(
                text("SELECT csc FROM emitters WHERE id = 'legacy-emitter'")
            ).scalar_one()
            ownership = connection.execute(
                text(
                    """
                    SELECT ce.consumer_id, ak.consumer_id, ak.scopes
                      FROM consumer_emitters ce
                      JOIN api_keys ak ON ak.id = 'legacy-key'
                     WHERE ce.emitter_id = 'legacy-emitter'
                    """
                )
            ).one()

        assert encrypted_csc != "legacy-csc-secret"
        assert EncryptedCertificateStore(encryption_key).decrypt_text(encrypted_csc) == (
            "legacy-csc-secret"
        )
        assert ownership[0] == ownership[1]
        assert "tenant:read" in ownership[2]
