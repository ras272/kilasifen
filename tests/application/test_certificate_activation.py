from datetime import UTC, date, datetime

import pytest

from kilasifen.domain.common.errors import DomainInvariantError
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.certificates.models import Certificate
from kilasifen.domain.stampings.models import Stamping
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.session import build_engine, build_session_factory, session_scope
from kilasifen.infrastructure.db.repositories.certificates import SqlAlchemyCertificateRepository
from kilasifen.infrastructure.db.repositories.emitters import SqlAlchemyEmitterRepository
from kilasifen.infrastructure.db.repositories.stampings import SqlAlchemyStampingRepository
from kilasifen.testing.database import managed_test_database_url


def test_active_certificate_selection_rejects_multiple_active_certificates(tmp_path) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="certificate_activation_multiple",
    ) as database_url:
        session_factory = _build_session_factory(database_url)

        emitter = Emitter(
            id="emitter-1",
            external_id="erp-1",
            ruc="80024135",
            dv="5",
            legal_name="ARES PARAGUAY SRL",
            tax_environment="test",
            status="active",
            csc=None,
            csc_id=None,
            created_at=_now(),
            updated_at=_now(),
        )
        first = Certificate(
            id="cert-1",
            emitter_id=emitter.id,
            logical_name="principal",
            encrypted_p12="encrypted-a",
            encrypted_password="encrypted-password-a",
            fingerprint="fingerprint-a",
            serial_number=None,
            subject_summary=None,
            detected_ruc="80024135",
            valid_from=None,
            valid_until=None,
            is_active=True,
            status="uploaded",
            created_at=_now(),
            updated_at=_now(),
        )
        second = Certificate(
            id="cert-2",
            emitter_id=emitter.id,
            logical_name="secundario",
            encrypted_p12="encrypted-b",
            encrypted_password="encrypted-password-b",
            fingerprint="fingerprint-b",
            serial_number=None,
            subject_summary=None,
            detected_ruc="80024135",
            valid_from=None,
            valid_until=None,
            is_active=True,
            status="uploaded",
            created_at=_now(),
            updated_at=_now(),
        )

        with session_scope(session_factory) as session:
            SqlAlchemyEmitterRepository(session).save(emitter)
            repo = SqlAlchemyCertificateRepository(session)
            repo.save(first)
            repo.save(second)

        with session_scope(session_factory) as session:
            repo = SqlAlchemyCertificateRepository(session)
            with pytest.raises(DomainInvariantError):
                repo.get_active_for_emitter(emitter.id)


def test_active_stamping_selection_is_scoped_to_emitter_and_date_window(tmp_path) -> None:
    with managed_test_database_url(
        tmp_path=tmp_path,
        name="certificate_activation_stamping",
    ) as database_url:
        session_factory = _build_session_factory(database_url)

        first_emitter = Emitter(
            id="emitter-1",
            external_id="erp-1",
            ruc="80024135",
            dv="5",
            legal_name="ARES PARAGUAY SRL",
            tax_environment="test",
            status="active",
            csc=None,
            csc_id=None,
            created_at=_now(),
            updated_at=_now(),
        )
        second_emitter = Emitter(
            id="emitter-2",
            external_id="erp-2",
            ruc="80099999",
            dv="1",
            legal_name="OTRA EMPRESA SA",
            tax_environment="test",
            status="active",
            csc=None,
            csc_id=None,
            created_at=_now(),
            updated_at=_now(),
        )

        valid_stamping = Stamping(
            id="stamp-1",
            emitter_id=first_emitter.id,
            number="80024135",
            start_date=date(2024, 3, 11),
            end_date=None,
            is_active=True,
            status="active",
            created_at=_now(),
            updated_at=_now(),
        )
        expired_stamping = Stamping(
            id="stamp-2",
            emitter_id=first_emitter.id,
            number="70000000",
            start_date=date(2023, 1, 1),
            end_date=date(2023, 12, 31),
            is_active=True,
            status="inactive",
            created_at=_now(),
            updated_at=_now(),
        )
        other_emitter_stamping = Stamping(
            id="stamp-3",
            emitter_id=second_emitter.id,
            number="90000000",
            start_date=date(2024, 1, 1),
            end_date=None,
            is_active=True,
            status="active",
            created_at=_now(),
            updated_at=_now(),
        )

        with session_scope(session_factory) as session:
            emitter_repo = SqlAlchemyEmitterRepository(session)
            emitter_repo.save(first_emitter)
            emitter_repo.save(second_emitter)

            repo = SqlAlchemyStampingRepository(session)
            repo.save(valid_stamping)
            repo.save(expired_stamping)
            repo.save(other_emitter_stamping)

        with session_scope(session_factory) as session:
            repo = SqlAlchemyStampingRepository(session)
            selected = repo.get_active_for_emitter(first_emitter.id, on_date=date(2024, 4, 24))

        assert selected is not None
        assert selected.id == valid_stamping.id


def _build_session_factory(database_url: str):
    engine = build_engine(database_url)
    Base.metadata.create_all(engine)
    return build_session_factory(engine)


def _now() -> datetime:
    return datetime.now(UTC)
