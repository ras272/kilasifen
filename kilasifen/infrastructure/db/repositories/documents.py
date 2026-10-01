"""SQLAlchemy implementation of the document repository."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from kilasifen.domain.documents.models import Document
from kilasifen.infrastructure.db.locks import locked_fresh
from kilasifen.infrastructure.db.models import DocumentModel
from kilasifen.repositories.documents import DocumentRepository


class SqlAlchemyDocumentRepository(DocumentRepository):
    """Persist documents with SQLAlchemy."""

    def __init__(self, session: Session):
        self.session = session

    def save(self, document: Document) -> Document:
        existing = self.session.get(DocumentModel, document.id)
        if existing is None:
            model = DocumentModel(
                id=document.id,
                emitter_id=document.emitter_id,
                external_id=document.external_id,
                idempotency_key=document.idempotency_key,
                document_type=document.document_type,
                payload_snapshot=document.payload_snapshot,
                generated_xml=document.generated_xml,
                signed_xml=document.signed_xml,
                sifen_request_xml=document.sifen_request_xml,
                sifen_response_raw=document.sifen_response_raw,
                last_query_request_xml=document.last_query_request_xml,
                last_query_response_raw=document.last_query_response_raw,
                last_query_at=document.last_query_at,
                cdc=document.cdc,
                internal_status=document.internal_status,
                sifen_status=document.sifen_status,
                sifen_result_code=document.sifen_result_code,
                sifen_result_message=document.sifen_result_message,
                establishment=document.establishment,
                point=document.point,
                document_number=document.document_number,
                created_at=document.created_at,
                updated_at=document.updated_at,
            )
            self.session.add(model)
        else:
            existing.external_id = document.external_id
            existing.idempotency_key = document.idempotency_key
            existing.document_type = document.document_type
            existing.payload_snapshot = document.payload_snapshot
            existing.generated_xml = document.generated_xml
            existing.signed_xml = document.signed_xml
            existing.sifen_request_xml = document.sifen_request_xml
            existing.sifen_response_raw = document.sifen_response_raw
            existing.last_query_request_xml = document.last_query_request_xml
            existing.last_query_response_raw = document.last_query_response_raw
            existing.last_query_at = document.last_query_at
            existing.cdc = document.cdc
            existing.internal_status = document.internal_status
            existing.sifen_status = document.sifen_status
            existing.sifen_result_code = document.sifen_result_code
            existing.sifen_result_message = document.sifen_result_message
            existing.establishment = document.establishment
            existing.point = document.point
            existing.document_number = document.document_number
            existing.updated_at = document.updated_at
        self.session.flush()
        return document

    def get(self, document_id: str) -> Document | None:
        model = self.session.get(DocumentModel, document_id)
        if model is None:
            return None
        return _to_domain(model)

    def get_for_update(self, document_id: str) -> Document | None:
        statement = select(DocumentModel).where(DocumentModel.id == document_id)
        model = self.session.scalar(locked_fresh(statement))
        if model is None:
            return None
        return _to_domain(model)

    def get_by_idempotency_key(self, emitter_id: str, idempotency_key: str) -> Document | None:
        statement = select(DocumentModel).where(
            DocumentModel.emitter_id == emitter_id,
            DocumentModel.idempotency_key == idempotency_key,
        )
        model = self.session.scalar(statement)
        if model is None:
            return None
        return _to_domain(model)

    def get_by_external_id(self, emitter_id: str, external_id: str) -> Document | None:
        statement = select(DocumentModel).where(
            DocumentModel.emitter_id == emitter_id,
            DocumentModel.external_id == external_id,
        )
        model = self.session.scalar(statement)
        if model is None:
            return None
        return _to_domain(model)

    def get_by_cdc(self, emitter_id: str, cdc: str) -> Document | None:
        statement = select(DocumentModel).where(
            DocumentModel.emitter_id == emitter_id,
            DocumentModel.cdc == cdc,
        )
        model = self.session.scalar(statement)
        if model is None:
            return None
        return _to_domain(model)

    def list_by_associated_cdc(self, *, emitter_id: str, associated_cdc: str) -> list[Document]:
        statement = select(DocumentModel).where(DocumentModel.emitter_id == emitter_id)
        models = list(self.session.scalars(statement))
        matched: list[Document] = []
        for model in models:
            snapshot = model.payload_snapshot if isinstance(model.payload_snapshot, dict) else None
            if not snapshot:
                continue
            typed_contract = snapshot.get("typed_contract")
            if not isinstance(typed_contract, dict):
                continue
            payload = typed_contract.get("payload")
            if not isinstance(payload, dict):
                continue
            asociado = payload.get("documento_asociado")
            if not isinstance(asociado, dict):
                continue
            if str(asociado.get("cdc") or "").strip() == associated_cdc:
                matched.append(_to_domain(model))
        return matched

    def list_numbers_in_range(
        self,
        *,
        emitter_id: str,
        document_type: str,
        establishment: str,
        point: str,
        number_from: int,
        number_to: int,
    ) -> list[int]:
        statement = select(DocumentModel.document_number).where(
            DocumentModel.emitter_id == emitter_id,
            DocumentModel.document_type == document_type,
            DocumentModel.establishment == establishment,
            DocumentModel.point == point,
            DocumentModel.document_number.is_not(None),
            DocumentModel.document_number >= number_from,
            DocumentModel.document_number <= number_to,
        )
        return sorted(int(number) for number in self.session.scalars(statement) if number is not None)

    def list_recent(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        emitter_id: str | None = None,
        internal_status: str | None = None,
        document_type: str | None = None,
        external_id: str | None = None,
        cdc: str | None = None,
    ) -> list[Document]:
        statement = select(DocumentModel)
        if emitter_id:
            statement = statement.where(DocumentModel.emitter_id == emitter_id)
        if internal_status:
            statement = statement.where(DocumentModel.internal_status == internal_status)
        if document_type:
            statement = statement.where(DocumentModel.document_type == document_type)
        if external_id:
            statement = statement.where(DocumentModel.external_id == external_id)
        if cdc:
            statement = statement.where(DocumentModel.cdc == cdc)
        statement = (
            statement.order_by(DocumentModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return [_to_domain(model) for model in self.session.scalars(statement)]


def _to_domain(model: DocumentModel) -> Document:
    return Document(
        id=model.id,
        emitter_id=model.emitter_id,
        external_id=model.external_id,
        idempotency_key=model.idempotency_key,
        document_type=model.document_type,
        payload_snapshot=model.payload_snapshot,
        generated_xml=model.generated_xml,
        signed_xml=model.signed_xml,
        sifen_request_xml=model.sifen_request_xml,
        sifen_response_raw=model.sifen_response_raw,
        last_query_request_xml=model.last_query_request_xml,
        last_query_response_raw=model.last_query_response_raw,
        last_query_at=model.last_query_at,
        cdc=model.cdc,
        internal_status=model.internal_status,
        sifen_status=model.sifen_status,
        sifen_result_code=model.sifen_result_code,
        sifen_result_message=model.sifen_result_message,
        created_at=model.created_at,
        updated_at=model.updated_at,
        establishment=model.establishment,
        point=model.point,
        document_number=model.document_number,
    )
