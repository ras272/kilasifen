"""Application service layer for read-side SIFEN queries.

SIFEN is queried with no row lock held: the emitter is checked without
``SELECT ... FOR UPDATE`` and the document is locked and re-read only after
the network call, right before the query trace and any reconciliation are
written.

A reconciliation records SIFEN's answer on the CDC (DECISIONES F62, F63)
and never sends anything:

- 0422 on a pending document makes it approved, or cancelled when
  ``xContEv`` holds a registered cancellation; on an approved document a
  registered cancellation makes it cancelled. The signed XML the platform
  issued is never replaced by the copy in ``xContenDE``.
- 0420 on a pending document that is not being sent right now settles a
  1001/1002 rejection waiting for this query, or queues the document: its
  next attempt sends the same signed DE again, and an aborted one (its job
  already failed) may also have its number inutilized.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from kilasifen.application.emitters.guards import (
    require_active_emitter_without_lock,
)
from kilasifen.domain.common.errors import ConflictError, NotFoundError
from kilasifen.domain.common.fiscal_states import (
    DOCUMENT_APPROVED_STATUSES,
    DOCUMENT_CANCELLED_STATUS,
    DOCUMENT_POSSIBLY_RECEIVED_STATUSES,
    DOCUMENT_SUBMITTING_STATUS,
)
from kilasifen.domain.documents.models import Document
from kilasifen.domain.emitters.models import Emitter
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.sifen.query import (
    QUERY_FOUND,
    QUERY_NOT_FOUND_OR_NOT_APPROVED,
    DocumentQueryOutcome,
    RucQueryOutcome,
    SifenQueryGateway,
)
from kilasifen.infrastructure.sifen.reconciliation import (
    document_found_at_sifen,
    document_not_approved_at_sifen,
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
        traced = replace(
            document,
            last_query_request_xml=outcome.request_xml,
            last_query_response_raw=outcome.response_raw,
            last_query_at=_now(),
            updated_at=_now(),
        )
        reconciled = None
        if reconcile:
            reconciled = _reconcile(
                replace(
                    traced,
                    sifen_result_code=outcome.result_code,
                    sifen_result_message=outcome.result_message,
                ),
                outcome,
            )
        if reconciled is None:
            return self.document_repository.save(traced), outcome
        self._close_emission_job(document, reconciled)
        return self.document_repository.save(reconciled), outcome

    def _close_emission_job(self, before: Document, after: Document) -> None:
        """Align the emission job with what the reconciliation recorded."""

        if after.internal_status == before.internal_status:
            return
        if after.internal_status not in {
            *DOCUMENT_APPROVED_STATUSES,
            DOCUMENT_CANCELLED_STATUS,
            "rejected",
        }:
            # Queued again: a scheduled job resends it; a failed one waits
            # for an operator retry (or the number is inutilized).
            return
        job = self.job_repository.get_for_entity("document", before.id)
        if job is None:
            raise ConflictError("jobs.missing_for_document")
        if after.internal_status == "rejected":
            closed = replace(
                job,
                status="failed",
                error_snapshot={
                    "category": "sifen_rejection",
                    "code": after.sifen_result_code,
                    "message": after.sifen_result_message,
                },
            )
        else:
            closed = replace(job, status="succeeded", error_snapshot=None)
        self.job_repository.save(
            replace(closed, finished_at=_now(), updated_at=_now())
        )

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


def _reconcile(document: Document, outcome: DocumentQueryOutcome) -> Document | None:
    """The document after SIFEN's answer, or ``None`` when nothing changes."""

    status = document.internal_status
    if outcome.status == QUERY_FOUND:
        if status in DOCUMENT_POSSIBLY_RECEIVED_STATUSES:
            return document_found_at_sifen(document, outcome)
        if status in DOCUMENT_APPROVED_STATUSES and outcome.cancelled:
            return document_found_at_sifen(document, outcome)
        return None
    if (
        outcome.status == QUERY_NOT_FOUND_OR_NOT_APPROVED
        and status in DOCUMENT_POSSIBLY_RECEIVED_STATUSES
        and status != DOCUMENT_SUBMITTING_STATUS
    ):
        # A document being sent right now is left to its worker.
        return document_not_approved_at_sifen(document)
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc)
