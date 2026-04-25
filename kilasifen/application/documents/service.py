"""Document application service layer."""

from datetime import UTC, datetime
from uuid import uuid4

from kilasifen.application.jobs.service import JobService
from kilasifen.domain.common.errors import ConflictError, NotFoundError
from kilasifen.domain.documents.models import Document
from kilasifen.domain.jobs.models import Job
from kilasifen.repositories.documents import DocumentRepository
from kilasifen.repositories.emitters import EmitterRepository


class DocumentService:
    """Use cases for documents."""

    def __init__(
        self,
        *,
        document_repository: DocumentRepository,
        emitter_repository: EmitterRepository,
        job_service: JobService,
    ):
        self.document_repository = document_repository
        self.emitter_repository = emitter_repository
        self.job_service = job_service

    def create_document(
        self,
        *,
        emitter_id: str,
        external_id: str | None,
        idempotency_key: str | None,
        document_type: str,
        payload_snapshot: dict | None,
    ) -> tuple[Document, Job, bool]:
        if self.emitter_repository.get(emitter_id) is None:
            raise NotFoundError("emitters.not_found")

        if idempotency_key:
            existing = self.document_repository.get_by_idempotency_key(
                emitter_id,
                idempotency_key,
            )
            if existing is not None:
                existing_job = self.job_service.get_for_entity("document", existing.id)
                if existing_job is None:
                    raise ConflictError("jobs.missing_for_document")
                return existing, existing_job, True

        if external_id:
            existing_external = self.document_repository.get_by_external_id(
                emitter_id,
                external_id,
            )
            if existing_external is not None:
                raise ConflictError("documents.external_id_conflict")

        timestamp = _now()
        document = Document(
            id=str(uuid4()),
            emitter_id=emitter_id,
            external_id=external_id,
            idempotency_key=idempotency_key,
            document_type=document_type,
            payload_snapshot=payload_snapshot,
            generated_xml=None,
            signed_xml=None,
            sifen_request_xml=None,
            sifen_response_raw=None,
            cdc=None,
            internal_status="queued",
            sifen_status=None,
            sifen_result_code=None,
            sifen_result_message=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        saved_document = self.document_repository.save(document)
        job = self.job_service.create_job(
            emitter_id=emitter_id,
            related_entity_type="document",
            related_entity_id=saved_document.id,
            job_type="document.emit",
        )
        return saved_document, job, False

    def get_document(self, document_id: str) -> Document:
        document = self.document_repository.get(document_id)
        if document is None:
            raise NotFoundError("documents.not_found")
        return document


def _now() -> datetime:
    return datetime.now(UTC)
