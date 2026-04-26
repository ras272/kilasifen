"""SQLAlchemy implementation of document numbering sequence repository."""

from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from kilasifen.domain.common.errors import ServiceUnavailableError
from kilasifen.domain.documents.numbering import DocumentNumberingSequence
from kilasifen.infrastructure.db.models import (
    DocumentNumberingSequenceModel,
    EventModel,
    InutilizedNumberRangeModel,
)
from kilasifen.repositories.document_numbering_sequences import (
    DocumentNumberingSequenceRepository,
)


class SqlAlchemyDocumentNumberingSequenceRepository(DocumentNumberingSequenceRepository):
    """Persist document numbering sequences with SQLAlchemy."""

    def __init__(self, session: Session):
        self.session = session

    def get_current(
        self,
        *,
        emitter_id: str,
        establishment: str,
        point: str,
        document_type: str,
    ) -> DocumentNumberingSequence | None:
        statement = select(DocumentNumberingSequenceModel).where(
            DocumentNumberingSequenceModel.emitter_id == emitter_id,
            DocumentNumberingSequenceModel.establishment == establishment,
            DocumentNumberingSequenceModel.point == point,
            DocumentNumberingSequenceModel.document_type == document_type,
        )
        model = self.session.scalar(statement)
        if model is None:
            return None
        return _to_domain(model)

    def reserve_next_number(
        self,
        *,
        emitter_id: str,
        establishment: str,
        point: str,
        document_type: str,
    ) -> int:
        backend = _backend_name(self.session)
        try:
            self._ensure_row_exists(
                backend=backend,
                emitter_id=emitter_id,
                establishment=establishment,
                point=point,
                document_type=document_type,
            )

            statement = select(DocumentNumberingSequenceModel).where(
                DocumentNumberingSequenceModel.emitter_id == emitter_id,
                DocumentNumberingSequenceModel.establishment == establishment,
                DocumentNumberingSequenceModel.point == point,
                DocumentNumberingSequenceModel.document_type == document_type,
            )
            if backend == "postgresql":
                self.session.execute(text("SET LOCAL lock_timeout = '5s'"))
                statement = statement.with_for_update()

            model = self.session.scalar(statement)
            if model is None:
                raise RuntimeError("Failed to load document numbering sequence.")

            model.last_number += 1
            candidate = int(model.last_number)
            while True:
                max_end = self._get_max_approved_inutilized_end_covering_number(
                    emitter_id=emitter_id,
                    document_type=document_type,
                    establishment=establishment,
                    point=point,
                    number=candidate,
                )
                if max_end is None:
                    break
                candidate = max_end + 1
            model.last_number = candidate
            self.session.flush()
            return int(model.last_number)
        except OperationalError as exc:
            if _is_postgres_lock_timeout(exc):
                raise ServiceUnavailableError("numbering.lock_timeout") from exc
            raise

    def _ensure_row_exists(
        self,
        *,
        backend: str,
        emitter_id: str,
        establishment: str,
        point: str,
        document_type: str,
    ) -> None:
        values = {
            "id": str(uuid4()),
            "emitter_id": emitter_id,
            "establishment": establishment,
            "point": point,
            "document_type": document_type,
            "last_number": 0,
        }
        if backend == "postgresql":
            statement = postgresql_insert(DocumentNumberingSequenceModel).values(**values)
            statement = statement.on_conflict_do_nothing(
                index_elements=[
                    "emitter_id",
                    "establishment",
                    "point",
                    "document_type",
                ]
            )
            self.session.execute(statement)
            self.session.flush()
            return

        if backend == "sqlite":
            statement = sqlite_insert(DocumentNumberingSequenceModel).values(**values)
            statement = statement.on_conflict_do_nothing(
                index_elements=[
                    "emitter_id",
                    "establishment",
                    "point",
                    "document_type",
                ]
            )
            self.session.execute(statement)
            self.session.flush()
            return

        # Fallback path for any other SQLAlchemy backend.
        existing = self.session.scalar(
            select(DocumentNumberingSequenceModel.id).where(
                DocumentNumberingSequenceModel.emitter_id == emitter_id,
                DocumentNumberingSequenceModel.establishment == establishment,
                DocumentNumberingSequenceModel.point == point,
                DocumentNumberingSequenceModel.document_type == document_type,
            )
        )
        if existing is None:
            self.session.add(DocumentNumberingSequenceModel(**values))
            self.session.flush()

    def _get_max_approved_inutilized_end_covering_number(
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
                InutilizedNumberRangeModel.numero_desde <= number,
                InutilizedNumberRangeModel.numero_hasta >= number,
                EventModel.status == "approved",
            )
        )
        value = self.session.scalar(statement)
        if value is None:
            return None
        return int(value)


def _backend_name(session: Session) -> str:
    bind = session.get_bind()
    if bind is None:
        return ""
    return bind.dialect.name


def _is_postgres_lock_timeout(exc: OperationalError) -> bool:
    original = getattr(exc, "orig", None)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return sqlstate in {"55P03", "57014"}


def _to_domain(model: DocumentNumberingSequenceModel) -> DocumentNumberingSequence:
    return DocumentNumberingSequence(
        id=model.id,
        emitter_id=model.emitter_id,
        establishment=model.establishment,
        point=model.point,
        document_type=model.document_type,
        last_number=model.last_number,
        updated_at=model.updated_at,
    )
