"""Application service layer for read-side SIFEN queries."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from kilasifen.domain.common.errors import ConflictError, NotFoundError
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


class QueryService:
    """Use cases for read-side SIFEN queries."""

    def __init__(
        self,
        *,
        emitter_repository: EmitterRepository,
        certificate_repository: CertificateRepository,
        document_repository: DocumentRepository,
        certificate_store: EncryptedCertificateStore,
        query_gateway: SifenQueryGateway,
    ):
        self.emitter_repository = emitter_repository
        self.certificate_repository = certificate_repository
        self.document_repository = document_repository
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
    ) -> tuple[Document, DocumentQueryOutcome]:
        emitter = self._get_emitter(emitter_id)
        document = self.document_repository.get(document_id)
        if document is None or document.emitter_id != emitter_id:
            raise NotFoundError("documents.not_found")
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
        updated = replace(
            document,
            last_query_request_xml=outcome.request_xml,
            last_query_response_raw=outcome.response_raw,
            last_query_at=_now(),
            sifen_status=outcome.status,
            sifen_result_code=outcome.result_code,
            sifen_result_message=outcome.result_message,
            updated_at=_now(),
        )
        return self.document_repository.save(updated), outcome

    def _get_emitter(self, emitter_id: str) -> Emitter:
        emitter = self.emitter_repository.get(emitter_id)
        if emitter is None:
            raise NotFoundError("emitters.not_found")
        return emitter

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
    return datetime.now(UTC)
