"""SQLAlchemy implementation of the document repository."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from kilasifen.domain.documents.models import Document
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
                cdc=document.cdc,
                internal_status=document.internal_status,
                sifen_status=document.sifen_status,
                sifen_result_code=document.sifen_result_code,
                sifen_result_message=document.sifen_result_message,
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
            existing.cdc = document.cdc
            existing.internal_status = document.internal_status
            existing.sifen_status = document.sifen_status
            existing.sifen_result_code = document.sifen_result_code
            existing.sifen_result_message = document.sifen_result_message
            existing.updated_at = document.updated_at
        self.session.flush()
        return document

    def get(self, document_id: str) -> Document | None:
        model = self.session.get(DocumentModel, document_id)
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
        cdc=model.cdc,
        internal_status=model.internal_status,
        sifen_status=model.sifen_status,
        sifen_result_code=model.sifen_result_code,
        sifen_result_message=model.sifen_result_message,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )
