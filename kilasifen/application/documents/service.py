"""Document application service layer."""

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from kilasifen.application.documents.fiscal_preflight import (
    check_emission_date,
    require_emitter_fiscal_identity,
    resolve_security_code,
    typed_fiscal_payload,
)
from kilasifen.application.documents.idempotency import (
    require_matching_idempotent_intent,
)
from kilasifen.application.documents.numbering_service import DocumentNumberingService
from kilasifen.application.emitters.guards import require_active_emitter
from kilasifen.application.jobs.service import JobService
from kilasifen.application.sandbox.service import SandboxOutcomePolicy
from kilasifen.domain.common.errors import ConflictError, NotFoundError
from kilasifen.domain.common.paraguay_time import paraguay_now
from kilasifen.domain.documents.kude_availability import (
    is_kude_available,
    normalize_kude_status,
)
from kilasifen.domain.documents.models import Document
from kilasifen.domain.jobs.models import Job
from kilasifen.domain.sandbox import SandboxOutcome
from kilasifen.repositories.documents import DocumentRepository
from kilasifen.repositories.emitters import EmitterRepository

logger = logging.getLogger(__name__)

_NUMBERED_TYPED_CONTRACTS = {
    "factura": "factura_v1",
    "nota_credito": "nota_credito_v1",
    "nota_debito": "nota_debito_v1",
}


class DocumentJobQueue(Protocol):
    """Queue contract for document emission jobs."""

    def enqueue_document_emit(
        self, job: Job, *, database_url: str, encryption_key: str
    ):
        """Enqueue one document emission job."""


class RawDocumentPayloadPolicy(Protocol):
    """Gate for payloads of the deprecated raw document route."""

    def __call__(self, payload_snapshot: dict | None) -> None:
        """Raise ``UnprocessableEntityError`` when the platform must not sign
        or transmit the XML the payload carries."""


class DocumentService:
    """Use cases for documents."""

    def __init__(
        self,
        *,
        document_repository: DocumentRepository,
        emitter_repository: EmitterRepository,
        job_service: JobService,
        numbering_service: DocumentNumberingService | None = None,
        queue: DocumentJobQueue | None = None,
        database_url: str | None = None,
        encryption_key: str | None = None,
        sandbox_policy: SandboxOutcomePolicy | None = None,
        raw_payload_policy: RawDocumentPayloadPolicy | None = None,
        clock: Callable[[], datetime] = paraguay_now,
    ):
        self.document_repository = document_repository
        self.emitter_repository = emitter_repository
        self.job_service = job_service
        self.numbering_service = numbering_service
        self.queue = queue
        self.database_url = database_url
        self.encryption_key = encryption_key
        self.sandbox_policy = sandbox_policy or SandboxOutcomePolicy("development")
        self.raw_payload_policy = raw_payload_policy
        self.clock = clock

    def create_document(
        self,
        *,
        emitter_id: str,
        external_id: str | None,
        idempotency_key: str | None,
        document_type: str,
        payload_snapshot: dict | None,
        sandbox_outcome: SandboxOutcome | None = None,
    ) -> tuple[Document, Job, bool]:
        return self._create_document(
            emitter_id=emitter_id,
            external_id=external_id,
            idempotency_key=idempotency_key,
            document_type=document_type,
            payload_snapshot=payload_snapshot,
            sandbox_outcome=sandbox_outcome,
        )

    def create_raw_document(
        self,
        *,
        emitter_id: str,
        external_id: str | None,
        idempotency_key: str | None,
        document_type: str,
        payload_snapshot: dict | None,
        sandbox_outcome: SandboxOutcome | None = None,
    ) -> tuple[Document, Job, bool]:
        """Create a document from the deprecated raw route.

        ``raw_payload_policy`` only applies to documents this call would
        create: a retry that resolves to an existing document (same
        idempotency key, or a taken ``external_id``) answers exactly as
        before, even when that document predates the policy. Without a
        configured policy the route fails closed.
        """

        if self.raw_payload_policy is None:
            raise RuntimeError("DocumentService has no raw_payload_policy.")
        return self._create_document(
            emitter_id=emitter_id,
            external_id=external_id,
            idempotency_key=idempotency_key,
            document_type=document_type,
            payload_snapshot=payload_snapshot,
            sandbox_outcome=sandbox_outcome,
            new_payload_policy=self.raw_payload_policy,
        )

    def _create_document(
        self,
        *,
        emitter_id: str,
        external_id: str | None,
        idempotency_key: str | None,
        document_type: str,
        payload_snapshot: dict | None,
        sandbox_outcome: SandboxOutcome | None,
        new_payload_policy: RawDocumentPayloadPolicy | None = None,
    ) -> tuple[Document, Job, bool]:
        payload_snapshot = self.sandbox_policy.apply(
            payload_snapshot,
            sandbox_outcome,
        )

        require_active_emitter(self.emitter_repository, emitter_id)

        if idempotency_key:
            existing = self.document_repository.get_by_idempotency_key(
                emitter_id,
                idempotency_key,
            )
            if existing is not None:
                require_matching_idempotent_intent(
                    existing,
                    external_id=external_id,
                    document_type=document_type,
                    payload_snapshot=payload_snapshot,
                    server_managed_numbering=self._uses_server_managed_numbering(
                        document_type=document_type,
                        payload_snapshot=payload_snapshot,
                    ),
                )
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

        if new_payload_policy is not None:
            new_payload_policy(payload_snapshot)

        fiscal_warnings: tuple[str, ...] = ()
        typed_payload = typed_fiscal_payload(payload_snapshot)
        if typed_payload is not None:
            self._require_fiscal_identity(emitter_id, typed_payload)
            fiscal_warnings = check_emission_date(typed_payload, now=self.clock())

        (
            normalized_payload_snapshot,
            establishment,
            point,
            document_number,
        ) = self._prepare_numbered_payload(
            emitter_id=emitter_id,
            document_type=document_type,
            payload_snapshot=payload_snapshot,
        )
        numbered_typed_payload = typed_fiscal_payload(normalized_payload_snapshot)
        security_code = (
            resolve_security_code(numbered_typed_payload)
            if numbered_typed_payload is not None
            else None
        )

        timestamp = _now()
        document = Document(
            id=str(uuid4()),
            emitter_id=emitter_id,
            external_id=external_id,
            idempotency_key=idempotency_key,
            document_type=document_type,
            payload_snapshot=normalized_payload_snapshot,
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
            establishment=establishment,
            point=point,
            document_number=document_number,
            security_code=security_code,
            fiscal_warnings=fiscal_warnings,
        )
        saved_document = self.document_repository.save(document)
        if fiscal_warnings:
            logger.warning(
                "documents.fiscal_warnings",
                extra={
                    "emitter_id": emitter_id,
                    "document_id": saved_document.id,
                    "fiscal_warnings": list(fiscal_warnings),
                },
            )
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

    def get_document_for_emitter(
        self, *, emitter_id: str, document_id: str
    ) -> Document:
        document = self.get_document(document_id)
        if document.emitter_id != emitter_id:
            raise NotFoundError("documents.not_found")
        return document

    def get_document_xml_for_emitter(self, *, emitter_id: str, document_id: str) -> str:
        document = self.get_document_for_emitter(
            emitter_id=emitter_id, document_id=document_id
        )
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

    def get_document_kude(self, *, emitter_id: str, document_id: str) -> bytes:
        from kilasifen.infrastructure.kude.pdf_renderer import render_kude_pdf

        document, emitter = self._resolve_kude_inputs(
            emitter_id=emitter_id, document_id=document_id
        )
        return render_kude_pdf(document=document, emitter=emitter)

    def get_document_kude_data(self, *, emitter_id: str, document_id: str) -> dict:
        from kilasifen.infrastructure.kude.data_extractor import extract_kude_data

        document, emitter = self._resolve_kude_inputs(
            emitter_id=emitter_id, document_id=document_id
        )
        return extract_kude_data(document=document, emitter=emitter)

    def _resolve_kude_inputs(self, *, emitter_id: str, document_id: str):
        document = self.get_document_for_emitter(
            emitter_id=emitter_id, document_id=document_id
        )
        if not is_kude_available(document.internal_status):
            # MT v150 §6.4; Dto 872/2023 Arts. 26, 30 and 31 (F51).
            raise ConflictError(
                "documents.kude_not_available",
                details={
                    "internal_status": normalize_kude_status(
                        document.internal_status
                    )
                },
            )
        emitter = self.emitter_repository.get(emitter_id)
        if emitter is None:
            raise NotFoundError("emitters.not_found")
        if not emitter.csc or not emitter.csc_id:
            raise ConflictError("emitters.csc_required")
        signed_xml = document.signed_xml
        if not signed_xml:
            payload = document.payload_snapshot or {}
            if isinstance(payload.get("signed_xml"), str):
                signed_xml = payload["signed_xml"]
        if not signed_xml:
            raise ConflictError("documents.signed_xml_not_available")
        if not document.signed_xml:
            document.signed_xml = signed_xml
        return document, emitter

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

    def _require_fiscal_identity(self, emitter_id: str, typed_payload: dict) -> None:
        emitter = self.emitter_repository.get_summary(emitter_id)
        if emitter is None:
            raise NotFoundError("emitters.not_found")
        require_emitter_fiscal_identity(emitter, typed_payload)

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

    def _prepare_numbered_payload(
        self,
        *,
        emitter_id: str,
        document_type: str,
        payload_snapshot: dict | None,
    ) -> tuple[dict | None, str | None, str | None, int | None]:
        if not isinstance(payload_snapshot, dict):
            return payload_snapshot, None, None, None
        if self.numbering_service is None:
            return payload_snapshot, None, None, None

        typed_contract = payload_snapshot.get("typed_contract")
        if not isinstance(typed_contract, dict):
            return payload_snapshot, None, None, None

        expected_contract = _NUMBERED_TYPED_CONTRACTS.get(document_type)
        contract = str(typed_contract.get("contract") or "").strip()
        if expected_contract is None or contract != expected_contract:
            return payload_snapshot, None, None, None

        typed_payload = typed_contract.get("payload")
        if not isinstance(typed_payload, dict):
            return payload_snapshot, None, None, None

        establishment = _normalize_three_digits(
            typed_payload.get("establecimiento"), default="001"
        )
        point = _normalize_three_digits(typed_payload.get("punto"), default="001")

        if typed_payload.get("numero") is not None:
            logger.warning(
                "documents.numbering.client_number_ignored",
                extra={
                    "emitter_id": emitter_id,
                    "document_type": document_type,
                    "establishment": establishment,
                    "point": point,
                    "client_number": typed_payload.get("numero"),
                },
            )

        next_number = self.numbering_service.reserve_next_number(
            emitter_id=emitter_id,
            establishment=establishment,
            point=point,
            document_type=document_type,
        )

        updated_typed_payload = dict(typed_payload)
        updated_typed_payload["establecimiento"] = establishment
        updated_typed_payload["punto"] = point
        updated_typed_payload["numero"] = next_number

        updated_typed_contract = dict(typed_contract)
        updated_typed_contract["payload"] = updated_typed_payload

        normalized_payload = dict(payload_snapshot)
        normalized_payload["typed_contract"] = updated_typed_contract
        normalized_payload["generated_xml"] = updated_typed_payload.get("generated_xml")
        normalized_payload["signed_xml"] = updated_typed_payload.get("signed_xml")
        normalized_payload["doc_id"] = updated_typed_payload.get("doc_id")
        return normalized_payload, establishment, point, next_number

    def _uses_server_managed_numbering(
        self,
        *,
        document_type: str,
        payload_snapshot: dict | None,
    ) -> bool:
        if self.numbering_service is None or not isinstance(payload_snapshot, dict):
            return False
        typed_contract = payload_snapshot.get("typed_contract")
        if not isinstance(typed_contract, dict):
            return False
        return typed_contract.get("contract") == _NUMBERED_TYPED_CONTRACTS.get(
            document_type
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_three_digits(value, *, default: str) -> str:
    if value is None:
        value = default
    return f"{int(str(value)):03d}"
