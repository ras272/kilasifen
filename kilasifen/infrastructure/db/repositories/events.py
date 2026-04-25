"""SQLAlchemy implementation of the event repository."""

from sqlalchemy.orm import Session

from kilasifen.domain.events.models import Event
from kilasifen.infrastructure.db.models import EventModel
from kilasifen.repositories.events import EventRepository


class SqlAlchemyEventRepository(EventRepository):
    """Persist events with SQLAlchemy."""

    def __init__(self, session: Session):
        self.session = session

    def save(self, event: Event) -> Event:
        existing = self.session.get(EventModel, event.id)
        if existing is None:
            model = EventModel(
                id=event.id,
                emitter_id=event.emitter_id,
                document_id=event.document_id,
                event_type=event.event_type,
                input_payload=event.input_payload,
                generated_xml=event.generated_xml,
                signed_xml=event.signed_xml,
                sifen_request_xml=event.sifen_request_xml,
                sifen_response_raw=event.sifen_response_raw,
                status=event.status,
                sifen_result_code=event.sifen_result_code,
                sifen_result_message=event.sifen_result_message,
                created_at=event.created_at,
                updated_at=event.updated_at,
            )
            self.session.add(model)
        else:
            existing.document_id = event.document_id
            existing.event_type = event.event_type
            existing.input_payload = event.input_payload
            existing.generated_xml = event.generated_xml
            existing.signed_xml = event.signed_xml
            existing.sifen_request_xml = event.sifen_request_xml
            existing.sifen_response_raw = event.sifen_response_raw
            existing.status = event.status
            existing.sifen_result_code = event.sifen_result_code
            existing.sifen_result_message = event.sifen_result_message
            existing.updated_at = event.updated_at

        self.session.flush()
        return event

    def get(self, event_id: str) -> Event | None:
        model = self.session.get(EventModel, event_id)
        if model is None:
            return None
        return _to_domain(model)


def _to_domain(model: EventModel) -> Event:
    return Event(
        id=model.id,
        emitter_id=model.emitter_id,
        document_id=model.document_id,
        event_type=model.event_type,
        input_payload=model.input_payload,
        generated_xml=model.generated_xml,
        signed_xml=model.signed_xml,
        sifen_request_xml=model.sifen_request_xml,
        sifen_response_raw=model.sifen_response_raw,
        status=model.status,
        sifen_result_code=model.sifen_result_code,
        sifen_result_message=model.sifen_result_message,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
