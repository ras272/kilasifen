"""SQLAlchemy implementation of the emitter repository."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from kilasifen.domain.emitters.models import Emitter
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.db.models import ConsumerEmitterModel, EmitterModel
from kilasifen.repositories.emitters import EmitterRepository


class SqlAlchemyEmitterRepository(EmitterRepository):
    """Persist emitters with SQLAlchemy."""

    def __init__(
        self,
        session: Session,
        secret_store: EncryptedCertificateStore | None = None,
    ):
        self.session = session
        self.secret_store = secret_store

    def save(self, emitter: Emitter) -> Emitter:
        existing = self.session.get(EmitterModel, emitter.id)
        if existing is None:
            model = EmitterModel(
                id=emitter.id,
                external_id=emitter.external_id,
                ruc=emitter.ruc,
                dv=emitter.dv,
                legal_name=emitter.legal_name,
                tax_environment=emitter.tax_environment,
                status=emitter.status,
                csc=self._encrypt_csc(emitter.csc),
                csc_id=emitter.csc_id,
                created_at=emitter.created_at,
                updated_at=emitter.updated_at,
            )
            self.session.add(model)
        else:
            existing.external_id = emitter.external_id
            existing.ruc = emitter.ruc
            existing.dv = emitter.dv
            existing.legal_name = emitter.legal_name
            existing.tax_environment = emitter.tax_environment
            existing.status = emitter.status
            existing.csc = self._encrypt_csc(emitter.csc)
            existing.csc_id = emitter.csc_id
            existing.updated_at = emitter.updated_at
        self.session.flush()
        return emitter

    def get(self, emitter_id: str) -> Emitter | None:
        model = self.session.get(EmitterModel, emitter_id)
        if model is None:
            return None
        return _to_domain(model, self.secret_store)

    def get_by_external_id(self, external_id: str) -> Emitter | None:
        statement = select(EmitterModel).where(EmitterModel.external_id == external_id)
        model = self.session.scalar(statement)
        if model is None:
            return None
        return _to_domain(model, self.secret_store)

    def get_by_tax_id(self, ruc: str, dv: str) -> Emitter | None:
        statement = select(EmitterModel).where(
            EmitterModel.ruc == ruc,
            EmitterModel.dv == dv,
        )
        model = self.session.scalar(statement)
        if model is None:
            return None
        return _to_domain(model, self.secret_store)

    def list_all(self) -> list[Emitter]:
        statement = select(EmitterModel).order_by(EmitterModel.created_at.desc())
        return [
            _to_domain(model, self.secret_store)
            for model in self.session.scalars(statement)
        ]

    def grant_owner(self, *, consumer_id: str, emitter_id: str) -> None:
        existing = self.session.scalar(
            select(ConsumerEmitterModel).where(
                ConsumerEmitterModel.emitter_id == emitter_id
            )
        )
        if existing is None:
            self.session.add(
                ConsumerEmitterModel(consumer_id=consumer_id, emitter_id=emitter_id)
            )
            self.session.flush()
            return
        if existing.consumer_id != consumer_id:
            raise ValueError("Emitter already belongs to another consumer")

    def _encrypt_csc(self, csc: str | None) -> str | None:
        if csc is None:
            return None
        if self.secret_store is None:
            raise RuntimeError("Encryption key is required to persist CSC material")
        return self.secret_store.encrypt_text(csc)


def _to_domain(
    model: EmitterModel,
    secret_store: EncryptedCertificateStore | None,
) -> Emitter:
    if model.csc is not None and secret_store is None:
        raise RuntimeError("Encryption key is required to read CSC material")
    return Emitter(
        id=model.id,
        external_id=model.external_id,
        ruc=model.ruc,
        dv=model.dv,
        legal_name=model.legal_name,
        tax_environment=model.tax_environment,
        status=model.status,
        csc=secret_store.decrypt_text(model.csc) if model.csc is not None else None,
        csc_id=model.csc_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
