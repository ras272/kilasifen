import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from kilasifen.application.documents.numbering_service import DocumentNumberingService
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.events.inutilized_ranges import InutilizedNumberRange
from kilasifen.domain.events.models import Event
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.repositories.document_numbering_sequences import (
    SqlAlchemyDocumentNumberingSequenceRepository,
)
from kilasifen.infrastructure.db.repositories.emitters import SqlAlchemyEmitterRepository
from kilasifen.infrastructure.db.repositories.events import SqlAlchemyEventRepository
from kilasifen.infrastructure.db.repositories.inutilized_number_ranges import (
    SqlAlchemyInutilizedNumberRangeRepository,
)
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


def test_reserve_next_number_skips_approved_inutilized_ranges(postgres_database_url: str) -> None:
    session_factory = _build_session_factory(postgres_database_url)
    _seed_emitter(session_factory, emitter_id="emitter-a", external_id="erp-a", ruc="80024135", dv="5")

    for run_index in range(5):
        point = f"{90 + run_index:03d}"
        for _ in range(9):
            _reserve_number(
                session_factory,
                emitter_id="emitter-a",
                establishment="001",
                point=point,
                document_type="factura",
            )

        _seed_approved_inutilization_range(
            session_factory,
            emitter_id="emitter-a",
            document_type="factura",
            establishment="001",
            point=point,
            numero_desde=10,
            numero_hasta=15,
        )

        next_number = _reserve_number(
            session_factory,
            emitter_id="emitter-a",
            establishment="001",
            point=point,
            document_type="factura",
        )
        assert next_number == 16


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


def _seed_approved_inutilization_range(
    session_factory,
    *,
    emitter_id: str,
    document_type: str,
    establishment: str,
    point: str,
    numero_desde: int,
    numero_hasta: int,
) -> None:
    timestamp = _now()
    event = Event(
        id=str(uuid4()),
        emitter_id=emitter_id,
        document_id=None,
        event_type="inutilize_numbers",
        input_payload=None,
        generated_xml="<gGroupGesEve/>",
        signed_xml="<gGroupGesEve/>",
        sifen_request_xml="<event-request/>",
        sifen_response_raw="<event-response/>",
        status="approved",
        sifen_result_code="0300",
        sifen_result_message="Evento procesado",
        created_at=timestamp,
        updated_at=timestamp,
    )
    range_item = InutilizedNumberRange(
        id=str(uuid4()),
        emitter_id=emitter_id,
        document_type=document_type,
        establishment=establishment,
        point=point,
        numero_desde=numero_desde,
        numero_hasta=numero_hasta,
        timbrado="80024135",
        event_id=event.id,
        sifen_protocol="90001234",
        created_at=timestamp,
        updated_at=timestamp,
    )
    with session_scope(session_factory) as session:
        SqlAlchemyEventRepository(session).save(event)
        SqlAlchemyInutilizedNumberRangeRepository(session).save(range_item)


def _now() -> datetime:
    return datetime.now(UTC)
