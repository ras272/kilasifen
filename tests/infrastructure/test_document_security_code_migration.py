import json
from pathlib import Path

from alembic.config import Config
from sqlalchemy import text

from alembic import command
from kilasifen.infrastructure.db.session import build_engine
from kilasifen.testing.database import managed_test_database_url

# MT v150 p. 211 CDC example; dCodSeg occupies positions 35-43.
_CDC = "01444444017001001001452822017012515873260988"


def _typed(payload: dict) -> str:
    return json.dumps(
        {"typed_contract": {"contract": "factura_v1", "payload": payload}}
    )


def test_upgrade_backfills_security_codes_without_inventing_cdcs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    with managed_test_database_url(
        tmp_path=tmp_path, name="document_security_code_upgrade"
    ) as url:
        config = Config(str(repo_root / "alembic.ini"))
        config.set_main_option("script_location", str(repo_root / "alembic"))
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        monkeypatch.setenv("KILA_SIFEN_DATABASE_URL", url)
        command.upgrade(config, "20261001_09")

        engine = build_engine(url)
        rows = [
            ("with-cdc", _CDC, _typed({"numero": 1}), 1),
            ("caller-code", None, _typed({"numero": 2, "codigo_seguridad": 77}), 2),
            ("generated", None, _typed({"numero": 3}), 3),
            ("raw", None, json.dumps({"generated_xml": "<rDE/>"}), None),
        ]
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO emitters
                        (id, ruc, dv, legal_name, tax_environment, status)
                    VALUES ('emitter-1', '44444401', '7', 'Emisor', 'test', 'active')
                    """
                )
            )
            for document_id, cdc, payload, number in rows:
                connection.execute(
                    text(
                        """
                        INSERT INTO documents
                            (id, emitter_id, document_type, payload_snapshot, cdc,
                             internal_status, document_number)
                        VALUES (:id, 'emitter-1', 'factura', :payload, :cdc,
                                'queued', :number)
                        """
                    ),
                    {
                        "id": document_id,
                        "payload": payload,
                        "cdc": cdc,
                        "number": number,
                    },
                )

        command.upgrade(config, "20261001_10")

        with engine.connect() as connection:
            codes = dict(
                connection.execute(
                    text("SELECT id, security_code FROM documents")
                ).all()
            )

        assert codes["with-cdc"] == "587326098"
        assert codes["caller-code"] == "000000077"
        assert codes["generated"] is not None
        assert len(codes["generated"]) == 9 and int(codes["generated"]) != 3
        assert codes["raw"] is None
