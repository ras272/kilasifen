"""Application service layer for read-side SIFEN queries.

SIFEN is queried with no row lock held: the emitter is checked without
``SELECT ... FOR UPDATE`` and the document is locked and re-read only after
the network call, right before the query trace and any reconciliation are
written.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from kilasifen.application.emitters.guards import (
    require_active_emitter_without_lock,
)
from kilasifen.domain.common.errors import ConflictError, NotFoundError
from kilasifen.domain.common.fiscal_states import DOCUMENT_POSSIBLY_RECEIVED_STATUSES
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.sifen.query import (
    DocumentQueryOutcome,
    RucQueryOutcome,
    SifenQueryGateway,
)
from kilasifen.repositories.certificates import CertificateRepository
from kilasifen.repositories.documents import DocumentRepository
from kilasifen.repositories.emitters import EmitterRepository
from kilasifen.repositories.jobs import JobRepository


class QueryService:
    """Use cases for read-side SIFEN queries."""

    def __init__(
        self,
        *,
        emitter_repository: EmitterRepository,
        certificate_repository: CertificateRepository,
        document_repository: DocumentRepository,
        job_repository: JobRepository,
        certificate_store: EncryptedCertificateStore,
        query_gateway: SifenQueryGateway,
    ):
        self.emitter_repository = emitter_repository
        self.certificate_repository = certificate_repository
        self.document_repository = document_repository
        self.job_repository = job_repository
        self.certificate_store = certificate_store
        self.query_gateway = query_gateway

    def query_ruc(self, *, emitter_id: str, ruc: str) -> RucQueryOutcome:
        emitter = self._get_emitter(emitter_id)
        certificate_bytes, certificate_password = self._get_active_certificate_material(
            emitter_id
        )
        return self.query_gateway.query_ruc(
            emitter=emitter,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
            ruc=ruc,
        )

    def query_document(
        self,
        *,
        emitter_id: str,
        document_id: str,
        reconcile: bool = False,
    ) -> tuple[Document, DocumentQueryOutcome]:
        emitter = self._get_emitter(emitter_id)
        document = self._get_document_for_emitter(
            emitter_id=emitter_id,
            document=self.document_repository.get(document_id),
        )
        if not document.cdc:
            raise ConflictError("documents.cdc_required_for_query")

        certificate_bytes, certificate_password = self._get_active_certificate_material(
            emitter_id
        )
        outcome = self.query_gateway.query_document(
            emitter=emitter,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
            cdc=document.cdc,
        )
        # A worker may have recorded an outcome while SIFEN answered: decide on
        # the committed row, locked until this request commits.
        document = self._get_document_for_emitter(
            emitter_id=emitter_id,
            document=self.document_repository.get_for_update(document_id),
        )
        updated = replace(
            document,
            last_query_request_xml=outcome.request_xml,
            last_query_response_raw=outcome.response_raw,
            last_query_at=_now(),
            updated_at=_now(),
        )
        if (
            reconcile
            and document.internal_status in DOCUMENT_POSSIBLY_RECEIVED_STATUSES
            and outcome.status == "found"
        ):
            signed_xml = outcome.content_xml or document.signed_xml
            if not signed_xml:
                raise ConflictError("queries.document_content_missing")
            updated = replace(
                updated,
                signed_xml=signed_xml,
                internal_status="approved",
                sifen_status="approved",
                sifen_result_code=outcome.result_code,
                sifen_result_message=outcome.result_message,
                updated_at=_now(),
            )
            job = self.job_repository.get_for_entity("document", document.id)
            if job is None:
                raise ConflictError("jobs.missing_for_document")
            self.job_repository.save(
                replace(
                    job,
                    status="succeeded",
                    error_snapshot=None,
                    finished_at=_now(),
                    updated_at=_now(),
                )
            )
        return self.document_repository.save(updated), outcome

    def _get_emitter(self, emitter_id: str) -> Emitter:
        require_active_emitter_without_lock(self.emitter_repository, emitter_id)
        emitter = self.emitter_repository.get(emitter_id)
        if emitter is None:
            raise NotFoundError("emitters.not_found")
        return emitter

    @staticmethod
    def _get_document_for_emitter(
        *,
        emitter_id: str,
        document: Document | None,
    ) -> Document:
        if document is None or document.emitter_id != emitter_id:
            raise NotFoundError("documents.not_found")
        return document

    def _get_active_certificate_material(
        self,
        emitter_id: str,
    ) -> tuple[bytes, str]:
        certificate = self.certificate_repository.get_active_for_emitter(emitter_id)
        if certificate is None:
            raise ConflictError("certificates.active_required")
        return (
            self.certificate_store.decrypt_bytes(certificate.encrypted_p12),
            self.certificate_store.decrypt_text(certificate.encrypted_password),
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)
