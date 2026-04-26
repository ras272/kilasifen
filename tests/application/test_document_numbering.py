import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kilasifen.application.documents.numbering_service import DocumentNumberingService
from kilasifen.domain.emitters.models import Emitter
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.repositories.document_numbering_sequences import (
    SqlAlchemyDocumentNumberingSequenceRepository,
)
from kilasifen.infrastructure.db.repositories.emitters import SqlAlchemyEmitterRepository
from kilasifen.infrastructure.db.session import build_engine, build_session_factory, session_scope
from kilasifen.testing.database import managed_test_database_url


pytestmark = pytest.mark.requires_postgres


@pytest.fixture
def postgres_database_url(tmp_path: Path) -> Iterator[str]:
    if not os.getenv("KILA_SIFEN_TEST_DATABASE_URL"):
        pytest.skip("KILA_SIFEN_TEST_DATABASE_URL is required for Postgres concurrency tests.")
    with managed_test_database_url(tmp_path=tmp_path, name="document_numbering") as database_url:
        yield database_url


def test_reserve_next_number_is_sequential(postgres_database_url: str) -> None:
    session_factory = _build_session_factory(postgres_database_url)
    _seed_emitter(session_factory, emitter_id="emitter-a", external_id="erp-a", ruc="80024135", dv="5")

    first = _reserve_number(
        session_factory,
        emitter_id="emitter-a",
        establishment="001",
        point="001",
        document_type="factura",
    )
    second = _reserve_number(
        session_factory,
        emitter_id="emitter-a",
        establishment="001",
        point="001",
        document_type="factura",
    )
    third = _reserve_number(
        session_factory,
        emitter_id="emitter-a",
        establishment="001",
        point="001",
        document_type="factura",
    )

    assert [first, second, third] == [1, 2, 3]


def test_reserve_next_number_is_isolated_between_sequences(postgres_database_url: str) -> None:
    session_factory = _build_session_factory(postgres_database_url)
    _seed_emitter(session_factory, emitter_id="emitter-a", external_id="erp-a", ruc="80024135", dv="5")
    _seed_emitter(session_factory, emitter_id="emitter-b", external_id="erp-b", ruc="80111111", dv="9")

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures_a = [
            executor.submit(
                _reserve_number,
                session_factory,
                emitter_id="emitter-a",
                establishment="001",
                point="001",
                document_type="factura",
            )
            for _ in range(10)
        ]
        futures_b = [
            executor.submit(
                _reserve_number,
                session_factory,
                emitter_id="emitter-b",
                establishment="001",
                point="001",
                document_type="factura",
            )
            for _ in range(10)
        ]

    numbers_a = sorted(future.result() for future in futures_a)
    numbers_b = sorted(future.result() for future in futures_b)
    assert numbers_a == list(range(1, 11))
    assert numbers_b == list(range(1, 11))

    emitter_a_by_point = [
        _reserve_number(
            session_factory,
            emitter_id="emitter-a",
            establishment="001",
            point="002",
            document_type="factura",
        )
        for _ in range(3)
    ]
    emitter_a_by_establishment = [
        _reserve_number(
            session_factory,
            emitter_id="emitter-a",
            establishment="002",
            point="001",
            document_type="factura",
        )
        for _ in range(2)
    ]
    emitter_a_by_type = [
        _reserve_number(
            session_factory,
            emitter_id="emitter-a",
            establishment="001",
            point="001",
            document_type="nota_credito",
        )
        for _ in range(4)
    ]

    assert emitter_a_by_point == [1, 2, 3]
    assert emitter_a_by_establishment == [1, 2]
    assert emitter_a_by_type == [1, 2, 3, 4]


def test_reserve_next_number_concurrency_is_deterministic(postgres_database_url: str) -> None:
    session_factory = _build_session_factory(postgres_database_url)
    _seed_emitter(session_factory, emitter_id="emitter-a", external_id="erp-a", ruc="80024135", dv="5")

    for run_index in range(5):
        point = f"{run_index + 10:03d}"
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [
                executor.submit(
                    _reserve_number,
                    session_factory,
                    emitter_id="emitter-a",
                    establishment="001",
                    point=point,
                    document_type="factura",
                )
                for _ in range(20)
            ]
        numbers = sorted(future.result() for future in futures)
        assert numbers == list(range(1, 21))


def _build_session_factory(database_url: str):
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def _seed_emitter(
    session_factory,
    *,
    emitter_id: str,
    external_id: str,
    ruc: str,
    dv: str,
) -> None:
    emitter = Emitter(
        id=emitter_id,
        external_id=external_id,
        ruc=ruc,
        dv=dv,
        legal_name=f"{external_id} SA",
        tax_environment="test",
        status="active",
        csc=None,
        csc_id=None,
        created_at=_now(),
        updated_at=_now(),
    )
    with session_scope(session_factory) as session:
        SqlAlchemyEmitterRepository(session).save(emitter)


def _reserve_number(
    session_factory,
    *,
    emitter_id: str,
    establishment: str,
    point: str,
    document_type: str,
) -> int:
    with session_scope(session_factory) as session:
        service = DocumentNumberingService(SqlAlchemyDocumentNumberingSequenceRepository(session))
        return service.reserve_next_number(
            emitter_id=emitter_id,
            establishment=establishment,
            point=point,
            document_type=document_type,
        )


def _now() -> datetime:
    return datetime.now(UTC)

