"""Document application service layer."""

from typing import Protocol
from datetime import UTC, datetime
from uuid import uuid4

from kilasifen.application.jobs.service import JobService
from kilasifen.domain.common.errors import ConflictError, NotFoundError
from kilasifen.domain.documents.models import Document
from kilasifen.domain.jobs.models import Job
from kilasifen.repositories.documents import DocumentRepository
from kilasifen.repositories.emitters import EmitterRepository


class DocumentJobQueue(Protocol):
    """Queue contract for document emission jobs."""

    def enqueue_document_emit(self, job: Job, *, database_url: str, encryption_key: str):
        """Enqueue one document emission job."""


class DocumentService:
    """Use cases for documents."""

    def __init__(
        self,
        *,
        document_repository: DocumentRepository,
        emitter_repository: EmitterRepository,
        job_service: JobService,
        queue: DocumentJobQueue | None = None,
        database_url: str | None = None,
        encryption_key: str | None = None,
    ):
        self.document_repository = document_repository
        self.emitter_repository = emitter_repository
        self.job_service = job_service
        self.queue = queue
        self.database_url = database_url
        self.encryption_key = encryption_key

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
            last_query_request_xml=None,
            last_query_response_raw=None,
            last_query_at=None,
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
        self._enqueue_if_configured(job)
        return saved_document, job, False

    def get_document(self, document_id: str) -> Document:
        document = self.document_repository.get(document_id)
        if document is None:
            raise NotFoundError("documents.not_found")
        return document

    def get_document_for_emitter(self, *, emitter_id: str, document_id: str) -> Document:
        document = self.get_document(document_id)
        if document.emitter_id != emitter_id:
            raise NotFoundError("documents.not_found")
        return document

    def get_document_xml(self, *, document_id: str) -> str:
        document = self.get_document(document_id)
        if document.signed_xml:
            return document.signed_xml
        if document.generated_xml:
            return document.generated_xml
        payload = document.payload_snapshot or {}
        if isinstance(payload.get("signed_xml"), str):
            return payload["signed_xml"]
        if isinstance(payload.get("generated_xml"), str):
            return payload["generated_xml"]
        raise ConflictError("documents.xml_not_available")

    def list_documents(
        self,
        *,
        emitter_id: str,
        limit: int = 50,
        offset: int = 0,
        internal_status: str | None = None,
        document_type: str | None = None,
        external_id: str | None = None,
        cdc: str | None = None,
    ) -> list[Document]:
        if self.emitter_repository.get(emitter_id) is None:
            raise NotFoundError("emitters.not_found")
        return self.document_repository.list_recent(
            limit=limit,
            offset=offset,
            emitter_id=emitter_id,
            internal_status=internal_status,
            document_type=document_type,
            external_id=external_id,
            cdc=cdc,
        )

    def _enqueue_if_configured(self, job: Job) -> None:
        if self.queue is None:
            return
        if not self.database_url or not self.encryption_key:
            return

        self.queue.enqueue_document_emit(
            job,
            database_url=self.database_url,
            encryption_key=self.encryption_key,
        )


def _now() -> datetime:
    return datetime.now(UTC)
