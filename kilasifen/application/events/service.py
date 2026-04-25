"""Application service layer for fiscal events."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from pysifen.sdk.errors import (
    SifenRejectionError,
    SifenTimeoutError,
    SifenTransportError,
    SifenValidationError,
)

from kilasifen.application.jobs.service import JobService
from kilasifen.domain.common.errors import ConflictError, NotFoundError
from kilasifen.domain.events.models import Event
from kilasifen.domain.jobs.models import Job
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.sifen.event import EventSubmissionGateway
from kilasifen.repositories.certificates import CertificateRepository
from kilasifen.repositories.documents import DocumentRepository
from kilasifen.repositories.emitters import EmitterRepository
from kilasifen.repositories.events import EventRepository
from kilasifen.repositories.jobs import JobRepository


class EventService:
    """Use cases for fiscal event lifecycle."""

    def __init__(
        self,
        *,
        event_repository: EventRepository,
        emitter_repository: EmitterRepository,
        document_repository: DocumentRepository,
        certificate_repository: CertificateRepository,
        job_repository: JobRepository,
        certificate_store: EncryptedCertificateStore,
        submission_gateway: EventSubmissionGateway,
    ):
        self.event_repository = event_repository
        self.emitter_repository = emitter_repository
        self.document_repository = document_repository
        self.certificate_repository = certificate_repository
        self.job_repository = job_repository
        self.job_service = JobService(job_repository)
        self.certificate_store = certificate_store
        self.submission_gateway = submission_gateway

    def create_event(
        self,
        *,
        emitter_id: str,
        document_id: str,
        event_type: str,
        input_payload: dict | None,
    ) -> tuple[Event, Job]:
        emitter = self.emitter_repository.get(emitter_id)
        if emitter is None:
            raise NotFoundError("emitters.not_found")

        document = self.document_repository.get(document_id)
        if document is None or document.emitter_id != emitter_id:
            raise NotFoundError("documents.not_found")

        certificate = self.certificate_repository.get_active_for_emitter(emitter_id)
        if certificate is None:
            raise ConflictError("certificates.active_required")

        timestamp = _now()
        event = Event(
            id=str(uuid4()),
            emitter_id=emitter_id,
            document_id=document_id,
            event_type=event_type,
            input_payload=input_payload,
            generated_xml=(input_payload or {}).get("event_xml")
            if isinstance(input_payload, dict)
            else None,
            signed_xml=None,
            sifen_request_xml=None,
            sifen_response_raw=None,
            status="queued",
            sifen_result_code=None,
            sifen_result_message=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        saved_event = self.event_repository.save(event)
        job = self.job_service.create_job(
            emitter_id=emitter_id,
            related_entity_type="event",
            related_entity_id=saved_event.id,
            job_type="event.submit",
        )

        certificate_bytes = self.certificate_store.decrypt_bytes(certificate.encrypted_p12)
        certificate_password = self.certificate_store.decrypt_text(certificate.encrypted_password)

        try:
            outcome = self.submission_gateway.submit_event(
                event=saved_event,
                emitter=emitter,
                certificate=certificate,
                certificate_bytes=certificate_bytes,
                certificate_password=certificate_password,
            )
            updated_event = replace(
                saved_event,
                generated_xml=outcome.generated_xml,
                signed_xml=outcome.signed_xml,
                sifen_request_xml=outcome.request_xml,
                sifen_response_raw=outcome.response_raw,
                status=outcome.status,
                sifen_result_code=outcome.result_code,
                sifen_result_message=outcome.result_message,
                updated_at=_now(),
            )
            updated_job = replace(job, status="succeeded", error_snapshot=None, updated_at=_now())
        except SifenValidationError as exc:
            updated_event = replace(
                saved_event,
                status="failed",
                sifen_result_message=str(exc),
                updated_at=_now(),
            )
            updated_job = replace(
                job,
                status="failed",
                error_snapshot={"category": "fiscal_validation", "message": str(exc)},
                updated_at=_now(),
            )
        except (SifenTimeoutError, SifenTransportError) as exc:
            updated_event = replace(
                saved_event,
                status="retry_pending",
                sifen_result_message=str(exc),
                updated_at=_now(),
            )
            updated_job = replace(
                job,
                status="retry_scheduled",
                error_snapshot={"category": "transport", "message": str(exc)},
                updated_at=_now(),
            )
        except SifenRejectionError as exc:
            updated_event = replace(
                saved_event,
                status="rejected",
                sifen_result_code=exc.code,
                sifen_result_message=exc.message,
                updated_at=_now(),
            )
            updated_job = replace(
                job,
                status="failed",
                error_snapshot={
                    "category": "sifen_rejection",
                    "code": exc.code,
                    "message": exc.message,
                },
                updated_at=_now(),
            )

        self.event_repository.save(updated_event)
        self.job_repository.save(updated_job)
        return updated_event, updated_job

    def get_event(self, event_id: str) -> tuple[Event, Job | None]:
        event = self.event_repository.get(event_id)
        if event is None:
            raise NotFoundError("events.not_found")
        job = self.job_service.get_for_entity("event", event.id)
        return event, job


def _now() -> datetime:
    return datetime.now(UTC)
