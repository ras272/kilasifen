"""SQLAlchemy repository for inutilized number ranges."""

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from kilasifen.domain.events.inutilized_ranges import InutilizedNumberRange
from kilasifen.infrastructure.db.models import EventModel, InutilizedNumberRangeModel
from kilasifen.repositories.inutilized_number_ranges import (
    InutilizedNumberRangeRepository,
)


class SqlAlchemyInutilizedNumberRangeRepository(InutilizedNumberRangeRepository):
    """Persist and query inutilized number ranges."""

    def __init__(self, session: Session):
        self.session = session

    def save(self, range_item: InutilizedNumberRange) -> InutilizedNumberRange:
        existing = self.session.get(InutilizedNumberRangeModel, range_item.id)
        if existing is None:
            model = InutilizedNumberRangeModel(
                id=range_item.id,
                emitter_id=range_item.emitter_id,
                document_type=range_item.document_type,
                establishment=range_item.establishment,
                point=range_item.point,
                numero_desde=range_item.numero_desde,
                numero_hasta=range_item.numero_hasta,
                timbrado=range_item.timbrado,
                event_id=range_item.event_id,
                sifen_protocol=range_item.sifen_protocol,
                created_at=range_item.created_at,
                updated_at=range_item.updated_at,
            )
            self.session.add(model)
        else:
            existing.document_type = range_item.document_type
            existing.establishment = range_item.establishment
            existing.point = range_item.point
            existing.numero_desde = range_item.numero_desde
            existing.numero_hasta = range_item.numero_hasta
            existing.timbrado = range_item.timbrado
            existing.event_id = range_item.event_id
            existing.sifen_protocol = range_item.sifen_protocol
            existing.updated_at = range_item.updated_at
        self.session.flush()
        return range_item

    def list_overlapping(
        self,
        *,
        emitter_id: str,
        document_type: str,
        establishment: str,
        point: str,
        number_from: int,
        number_to: int,
        approved_only: bool = False,
    ) -> list[InutilizedNumberRange]:
        statement = (
            select(InutilizedNumberRangeModel)
            .where(
                InutilizedNumberRangeModel.emitter_id == emitter_id,
                InutilizedNumberRangeModel.document_type == document_type,
                InutilizedNumberRangeModel.establishment == establishment,
                InutilizedNumberRangeModel.point == point,
                InutilizedNumberRangeModel.numero_desde <= number_to,
                InutilizedNumberRangeModel.numero_hasta >= number_from,
            )
            .order_by(
                InutilizedNumberRangeModel.numero_desde.asc(),
                InutilizedNumberRangeModel.created_at.asc(),
            )
        )
        if approved_only:
            statement = statement.join(
                EventModel, EventModel.id == InutilizedNumberRangeModel.event_id
            ).where(EventModel.status == "approved")

        return [_to_domain(model) for model in self.session.scalars(statement)]

    def get_for_event(self, event_id: str) -> InutilizedNumberRange | None:
        statement = select(InutilizedNumberRangeModel).where(
            InutilizedNumberRangeModel.event_id == event_id
        )
        model = self.session.scalars(statement).first()
        return _to_domain(model) if model is not None else None

    def get_max_approved_end_covering_number(
        self,
        *,
        emitter_id: str,
        document_type: str,
        establishment: str,
        point: str,
        number: int,
    ) -> int | None:
        statement = (
            select(func.max(InutilizedNumberRangeModel.numero_hasta))
            .select_from(InutilizedNumberRangeModel)
            .join(EventModel, EventModel.id == InutilizedNumberRangeModel.event_id)
            .where(
                InutilizedNumberRangeModel.emitter_id == emitter_id,
                InutilizedNumberRangeModel.document_type == document_type,
                InutilizedNumberRangeModel.establishment == establishment,
                InutilizedNumberRangeModel.point == point,
                EventModel.status == "approved",
                and_(
                    InutilizedNumberRangeModel.numero_desde <= number,
                    InutilizedNumberRangeModel.numero_hasta >= number,
                ),
            )
        )
        value = self.session.scalar(statement)
        if value is None:
            return None
        return int(value)


def _to_domain(model: InutilizedNumberRangeModel) -> InutilizedNumberRange:
    return InutilizedNumberRange(
        id=model.id,
        emitter_id=model.emitter_id,
        document_type=model.document_type,
        establishment=model.establishment,
        point=model.point,
        numero_desde=model.numero_desde,
        numero_hasta=model.numero_hasta,
        timbrado=model.timbrado,
        event_id=model.event_id,
        sifen_protocol=model.sifen_protocol,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
