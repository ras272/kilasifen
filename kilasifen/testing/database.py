"""Database helpers for tests."""

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import re
import uuid

from sqlalchemy import text
from sqlalchemy.engine.url import make_url

from kilasifen.infrastructure.db.session import build_engine

_SCHEMA_SAFE_RE = re.compile(r"[^a-z0-9_]+")


@contextmanager
def managed_test_database_url(*, tmp_path: Path, name: str) -> Iterator[str]:
    """Yield an isolated database URL for each test."""

    postgres_url = os.getenv("KILA_SIFEN_TEST_DATABASE_URL")
    if not postgres_url:
        yield f"sqlite:///{tmp_path / f'{name}.db'}"
        return

    parsed = make_url(postgres_url)
    backend = parsed.get_backend_name()
    if backend not in {"postgresql", "postgres"}:
        raise ValueError("KILA_SIFEN_TEST_DATABASE_URL must point to PostgreSQL.")

    schema_suffix = _SCHEMA_SAFE_RE.sub("_", name.lower()).strip("_")[:24] or "test"
    schema = f"t_{schema_suffix}_{uuid.uuid4().hex[:8]}"

    admin_engine = build_engine(postgres_url)
    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        yield _build_schema_scoped_url(postgres_url, schema)
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def _build_schema_scoped_url(database_url: str, schema: str) -> str:
    parsed = make_url(database_url)
    query = dict(parsed.query)
    options = query.get("options", "")
    extra_option = f"-csearch_path={schema}"
    query["options"] = f"{options} {extra_option}".strip()
    return parsed.set(query=query).render_as_string(hide_password=False)

