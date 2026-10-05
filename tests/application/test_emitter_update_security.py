from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet

from kilasifen.application.emitters.service import EmitterService
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.base import Base
from kilasifen.infrastructure.db.models import EmitterModel
from kilasifen.infrastructure.db.repositories.emitters import (
    SqlAlchemyEmitterRepository,
)
from kilasifen.infrastructure.db.session import (
    build_engine,
    build_session_factory,
    session_scope,
)

_EMITTER_ID = "emitter-update-security"
_OLD_CSC = "OLDCSC00000000000000000000000001"
_NEW_CSC = "NEWCSC00000000000000000000000002"


class _FailOnSecretAccess:
    def encrypt_text(self, raw_value: str) -> str:
        del raw_value
        raise AssertionError("metadata update attempted to encrypt CSC")

    def decrypt_text(self, encrypted_value: str) -> str:
        del encrypted_value
        raise AssertionError("metadata update attempted to decrypt CSC")


class _TrackingRepository(SqlAlchemyEmitterRepository):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lock_calls = 0

    def get_status_for_update(self, emitter_id: str) -> str | None:
        self.lock_calls += 1
        return super().get_status_for_update(emitter_id)


class _InterleavingMetadataRepository(SqlAlchemyEmitterRepository):
    def __init__(self, *args, before_update: Callable[[], None], **kwargs):
        super().__init__(*args, **kwargs)
        self.before_update = before_update

    def update_metadata(self, *args, **kwargs):
        self.before_update()
        return super().update_metadata(*args, **kwargs)


def test_metadata_update_never_uses_the_secret_store(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'metadata-no-secret.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    _seed_emitter(factory, encrypted_csc="opaque-ciphertext")

    with session_scope(factory) as session:
        repository = SqlAlchemyEmitterRepository(session, _FailOnSecretAccess())
        result = EmitterService(repository).update_emitter(
            _EMITTER_ID,
            legal_name="Metadata only",
            tax_environment=None,
            csc=None,
            csc_id=None,
        )

    assert result.legal_name == "Metadata only"
    assert result.csc_configured is True
    assert result.csc_id == "0001"
    with session_scope(factory) as session:
        persisted = session.get(EmitterModel, _EMITTER_ID)
        assert persisted is not None
        assert persisted.csc == "opaque-ciphertext"


def test_metadata_update_cannot_restore_a_concurrently_rotated_csc(
    tmp_path: Path,
) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'metadata-race.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    store = EncryptedCertificateStore(Fernet.generate_key().decode())
    _seed_emitter(factory, encrypted_csc=store.encrypt_text(_OLD_CSC))
    rotation_observation: dict[str, object] = {}

    def rotate_secret() -> None:
        with session_scope(factory) as rotation_session:
            repository = _TrackingRepository(rotation_session, store)
            result = EmitterService(repository).update_emitter(
                _EMITTER_ID,
                legal_name=None,
                tax_environment=None,
                csc=_NEW_CSC,
                csc_id="0002",
            )
            rotation_observation["lock_calls"] = repository.lock_calls
            rotation_observation["result"] = result

    with session_scope(factory) as metadata_session:
        repository = _InterleavingMetadataRepository(
            metadata_session,
            store,
            before_update=rotate_secret,
        )
        metadata_result = EmitterService(repository).update_emitter(
            _EMITTER_ID,
            legal_name="Metadata after rotation",
            tax_environment=None,
            csc=None,
            csc_id=None,
        )

    assert rotation_observation["lock_calls"] == 1
    assert metadata_result.legal_name == "Metadata after rotation"
    with session_scope(factory) as session:
        persisted = session.get(EmitterModel, _EMITTER_ID)
        assert persisted is not None
        assert store.decrypt_text(persisted.csc) == _NEW_CSC
        assert persisted.csc_id == "0002"


def _seed_emitter(factory, *, encrypted_csc: str) -> None:
    timestamp = datetime.now(timezone.utc)
    with session_scope(factory) as session:
        session.add(
            EmitterModel(
                id=_EMITTER_ID,
                external_id="security-test",
                ruc="80000001",
                dv="3",
                legal_name="Before",
                tax_environment="test",
                status="active",
                csc=encrypted_csc,
                csc_id="0001",
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
