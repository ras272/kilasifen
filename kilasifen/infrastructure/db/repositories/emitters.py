"""SQLAlchemy implementation of the emitter repository."""

from sqlalchemy.orm import Session

from kilasifen.domain.emitters.models import Emitter
from kilasifen.infrastructure.db.models import EmitterModel
from kilasifen.repositories.emitters import EmitterRepository


class SqlAlchemyEmitterRepository(EmitterRepository):
    """Persist emitters with SQLAlchemy."""

    def __init__(self, session: Session):
        self.session = session

    def save(self, emitter: Emitter) -> Emitter:
        model = EmitterModel(
            id=emitter.id,
            external_id=emitter.external_id,
            ruc=emitter.ruc,
            dv=emitter.dv,
            legal_name=emitter.legal_name,
            tax_environment=emitter.tax_environment,
            status=emitter.status,
            csc=emitter.csc,
            csc_id=emitter.csc_id,
            created_at=emitter.created_at,
            updated_at=emitter.updated_at,
        )
        self.session.merge(model)
        return emitter

    def get(self, emitter_id: str) -> Emitter | None:
        model = self.session.get(EmitterModel, emitter_id)
        if model is None:
            return None
        return Emitter(
            id=model.id,
            external_id=model.external_id,
            ruc=model.ruc,
            dv=model.dv,
            legal_name=model.legal_name,
            tax_environment=model.tax_environment,
            status=model.status,
            csc=model.csc,
            csc_id=model.csc_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
