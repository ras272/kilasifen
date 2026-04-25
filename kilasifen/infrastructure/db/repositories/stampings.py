"""SQLAlchemy implementation of the stamping repository."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from kilasifen.domain.stampings.models import Stamping, select_active_stamping
from kilasifen.infrastructure.db.models import StampingModel
from kilasifen.repositories.stampings import StampingRepository


class SqlAlchemyStampingRepository(StampingRepository):
    """Persist stampings with SQLAlchemy."""

    def __init__(self, session: Session):
        self.session = session

    def save(self, stamping: Stamping) -> Stamping:
        existing = self.session.get(StampingModel, stamping.id)
        if existing is None:
            model = StampingModel(
                id=stamping.id,
                emitter_id=stamping.emitter_id,
                number=stamping.number,
                start_date=stamping.start_date,
                end_date=stamping.end_date,
                is_active=stamping.is_active,
                status=stamping.status,
                created_at=stamping.created_at,
                updated_at=stamping.updated_at,
            )
            self.session.add(model)
        else:
            existing.number = stamping.number
            existing.start_date = stamping.start_date
            existing.end_date = stamping.end_date
            existing.is_active = stamping.is_active
            existing.status = stamping.status
            existing.updated_at = stamping.updated_at
        self.session.flush()
        return stamping

    def list_for_emitter(self, emitter_id: str) -> list[Stamping]:
        statement = select(StampingModel).where(StampingModel.emitter_id == emitter_id)
        models = self.session.scalars(statement).all()
        return [_to_domain(model) for model in models]

    def get_active_for_emitter(self, emitter_id: str, on_date: date) -> Stamping | None:
        stampings = self.list_for_emitter(emitter_id)
        return select_active_stamping(stampings, emitter_id, on_date)

    def get(self, stamping_id: str) -> Stamping | None:
        model = self.session.get(StampingModel, stamping_id)
        if model is None:
            return None
        return _to_domain(model)

    def deactivate_others(self, emitter_id: str, active_stamping_id: str) -> None:
        statement = select(StampingModel).where(
            StampingModel.emitter_id == emitter_id,
            StampingModel.id != active_stamping_id,
            StampingModel.is_active.is_(True),
        )
        for model in self.session.scalars(statement):
            model.is_active = False
            model.status = "inactive"
        self.session.flush()


def _to_domain(model: StampingModel) -> Stamping:
    return Stamping(
        id=model.id,
        emitter_id=model.emitter_id,
        number=model.number,
        start_date=model.start_date,
        end_date=model.end_date,
        is_active=model.is_active,
        status=model.status,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
