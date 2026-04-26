"""Application service layer for fiscal events."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import logging
from typing import Protocol
from uuid import uuid4

from pysifen.sdk.errors import (
    SifenRejectionError,
    SifenTimeoutError,
    SifenTransportError,
    SifenValidationError,
)

from kilasifen.application.jobs.service import JobService
from kilasifen.domain.common.errors import ConflictError, NotFoundError, UnprocessableEntityError
from kilasifen.domain.documents.models import Document
from kilasifen.domain.events.inutilized_ranges import InutilizedNumberRange
from kilasifen.domain.events.models import Event
from kilasifen.domain.jobs.models import Job
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.sifen.event import EventSubmissionGateway
from kilasifen.infrastructure.sifen.typed_event_builder import (
    build_signed_cancel_event_group_xml,
    build_signed_inutilization_event_group_xml,
)
from kilasifen.repositories.document_numbering_sequences import DocumentNumberingSequenceRepository
from kilasifen.repositories.certificates import CertificateRepository
from kilasifen.repositories.documents import DocumentRepository
from kilasifen.repositories.emitters import EmitterRepository
from kilasifen.repositories.events import EventRepository
from kilasifen.repositories.inutilized_number_ranges import InutilizedNumberRangeRepository
from kilasifen.repositories.jobs import JobRepository

logger = logging.getLogger(__name__)

_CANCEL_EVENT_TYPE = "cancel_document"
_INUTILIZATION_EVENT_TYPE = "inutilize_numbers"

_DOC_TYPE_TO_ITIDE = {
    "factura": 1,
    "fe_exportacion": 2,
    "fe_importacion": 3,
    "autofactura": 4,
    "nota_credito": 5,
    "nota_debito": 6,
    "nota_remision": 7,
    "comprobante_retencion": 8,
}

_CANCEL_DEADLINE_HOURS = {
    "factura": 48,
    "nota_credito": 168,
    "nota_debito": 168,
    "nota_remision": 168,
    "autofactura": 168,
}

_APPROVED_DOCUMENT_STATUSES = {"approved", "approved_with_observation"}
_CANCELLED_DOCUMENT_STATUSES = {"cancelled"}


class WebhookPublisher(Protocol):
    """Minimal webhook publishing contract used by EventService."""

    def publish_event(
        self,
        *,
        emitter_id: str,
        event_type: str,
        payload: dict | None,
    ) -> list[tuple]:
        """Publish one event to subscribed webhook endpoints."""


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
        numbering_repository: DocumentNumberingSequenceRepository | None = None,
        inutilized_range_repository: InutilizedNumberRangeRepository | None = None,
        webhook_publisher: WebhookPublisher | None = None,
    ):
        self.event_repository = event_repository
        self.emitter_repository = emitter_repository
        self.document_repository = document_repository
        self.certificate_repository = certificate_repository
        self.job_repository = job_repository
        self.job_service = JobService(job_repository)
        self.certificate_store = certificate_store
        self.submission_gateway = submission_gateway
        self.numbering_repository = numbering_repository
        self.inutilized_range_repository = inutilized_range_repository
        self.webhook_publisher = webhook_publisher

    def create_event(
        self,
        *,
        emitter_id: str,
        document_id: str,
        event_type: str,
        input_payload: dict | None,
    ) -> tuple[Event, Job]:
        emitter, certificate, certificate_bytes, certificate_password = (
            self._resolve_emitter_and_active_certificate(emitter_id)
        )

        self._get_document_for_emitter(emitter_id=emitter_id, document_id=document_id)

        event, job, _ = self._create_and_submit_event(
            emitter_id=emitter_id,
            document_id=document_id,
            event_type=event_type,
            input_payload=input_payload,
            emitter=emitter,
            certificate=certificate,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
        )
        return event, job

    def cancel_document(
        self,
        *,
        emitter_id: str,
        document_id: str,
        motivo: str,
    ) -> tuple[Event, Job]:
        emitter, certificate, certificate_bytes, certificate_password = (
            self._resolve_emitter_and_active_certificate(emitter_id)
        )
        document = self._get_document_for_emitter(emitter_id=emitter_id, document_id=document_id)
        self._validate_cancelation(document=document)

        event_xml = build_signed_cancel_event_group_xml(
            cdc=document.cdc or "",
            motivo=motivo,
            signed_at=_now(),
            event_id=_generate_short_numeric_event_id(),
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
        )
        payload = {
            "event_xml": event_xml,
            "typed_contract": {
                "contract": "cancel_document_v1",
                "payload": {
                    "cdc": document.cdc,
                    "motivo": motivo,
                },
            },
        }
        event, job, _ = self._create_and_submit_event(
            emitter_id=emitter_id,
            document_id=document_id,
            event_type=_CANCEL_EVENT_TYPE,
            input_payload=payload,
            emitter=emitter,
            certificate=certificate,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
        )

        if event.status == "approved":
            self.document_repository.save(
                replace(
                    document,
                    internal_status="cancelled",
                    sifen_status="cancelled",
                    updated_at=_now(),
                )
            )
            self._publish_webhook_event(
                emitter_id=emitter_id,
                event_type="document.cancelled",
                payload={
                    "document_id": document.id,
                    "cdc": document.cdc,
                    "event_id": event.id,
                },
            )
        return event, job

    def inutilize_numbers(
        self,
        *,
        emitter_id: str,
        timbrado: str,
        document_type: str,
        establishment: str,
        point: str,
        numero_desde: int,
        numero_hasta: int,
        motivo: str,
    ) -> tuple[Event, Job, InutilizedNumberRange]:
        emitter, certificate, certificate_bytes, certificate_password = (
            self._resolve_emitter_and_active_certificate(emitter_id)
        )
        if self.inutilized_range_repository is None:
            raise RuntimeError("inutilized_range_repository is required")

        normalized_document_type = str(document_type).strip().lower()
        i_tide = _DOC_TYPE_TO_ITIDE.get(normalized_document_type)
        if i_tide is None:
            raise UnprocessableEntityError("events.inutilize.invalid_document_type")
        normalized_est = _normalize_three_digits(establishment)
        normalized_point = _normalize_three_digits(point)

        if numero_hasta < numero_desde:
            raise UnprocessableEntityError("events.inutilize.invalid_range")

        size = numero_hasta - numero_desde + 1
        if size > 1000:
            raise UnprocessableEntityError("events.inutilize.range_too_large")

        self._validate_inutilization_deadline(
            emitter_id=emitter_id,
            document_type=normalized_document_type,
            establishment=normalized_est,
            point=normalized_point,
            numero_hasta=numero_hasta,
        )

        used_numbers = self.document_repository.list_numbers_in_range(
            emitter_id=emitter_id,
            document_type=normalized_document_type,
            establishment=normalized_est,
            point=normalized_point,
            number_from=numero_desde,
            number_to=numero_hasta,
        )
        if used_numbers:
            raise ConflictError(
                "events.inutilize.range_already_used",
                details={"collisions": used_numbers},
            )

        overlapping_ranges = self.inutilized_range_repository.list_overlapping(
            emitter_id=emitter_id,
            document_type=normalized_document_type,
            establishment=normalized_est,
            point=normalized_point,
            number_from=numero_desde,
            number_to=numero_hasta,
            approved_only=True,
        )
        if overlapping_ranges:
            raise ConflictError(
                "events.inutilize.range_already_inutilized",
                details={
                    "ranges": [
                        {"desde": item.numero_desde, "hasta": item.numero_hasta}
                        for item in overlapping_ranges
                    ]
                },
            )

        event_xml = build_signed_inutilization_event_group_xml(
            timbrado=timbrado,
            i_tide=i_tide,
            establishment=normalized_est,
            point=normalized_point,
            numero_desde=numero_desde,
            numero_hasta=numero_hasta,
            motivo=motivo,
            signed_at=_now(),
            event_id=_generate_short_numeric_event_id(),
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
        )
        payload = {
            "event_xml": event_xml,
            "typed_contract": {
                "contract": "inutilize_numbers_v1",
                "payload": {
                    "timbrado": timbrado,
                    "document_type": normalized_document_type,
                    "establishment": normalized_est,
                    "point": normalized_point,
                    "numero_desde": numero_desde,
                    "numero_hasta": numero_hasta,
                    "motivo": motivo,
                    "i_tide": i_tide,
                },
            },
        }
        event, job, protocol = self._create_and_submit_event(
            emitter_id=emitter_id,
            document_id=None,
            event_type=_INUTILIZATION_EVENT_TYPE,
            input_payload=payload,
            emitter=emitter,
            certificate=certificate,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
        )

        timestamp = _now()
        range_item = InutilizedNumberRange(
            id=str(uuid4()),
            emitter_id=emitter_id,
            document_type=normalized_document_type,
            establishment=normalized_est,
            point=normalized_point,
            numero_desde=numero_desde,
            numero_hasta=numero_hasta,
            timbrado=str(timbrado).strip(),
            event_id=event.id,
            sifen_protocol=protocol if event.status == "approved" else None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        saved_range = self.inutilized_range_repository.save(range_item)

        if event.status == "approved":
            self._publish_webhook_event(
                emitter_id=emitter_id,
                event_type="numbering.inutilized",
                payload={
                    "event_id": event.id,
                    "document_type": normalized_document_type,
                    "establishment": normalized_est,
                    "point": normalized_point,
                    "numero_desde": numero_desde,
                    "numero_hasta": numero_hasta,
                    "timbrado": timbrado,
                    "sifen_protocol": protocol,
                },
            )
        return event, job, saved_range

    def get_event(self, event_id: str) -> tuple[Event, Job | None]:
        event = self.event_repository.get(event_id)
        if event is None:
            raise NotFoundError("events.not_found")
        job = self.job_service.get_for_entity("event", event.id)
        return event, job

    def _create_and_submit_event(
        self,
        *,
        emitter_id: str,
        document_id: str | None,
        event_type: str,
        input_payload: dict | None,
        emitter,
        certificate,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> tuple[Event, Job, str | None]:
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
        updated_event, updated_job, protocol = self._submit_event(
            saved_event=saved_event,
            job=job,
            emitter=emitter,
            certificate=certificate,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
        )
        self.event_repository.save(updated_event)
        self.job_repository.save(updated_job)
        return updated_event, updated_job, protocol

    def _submit_event(
        self,
        *,
        saved_event: Event,
        job: Job,
        emitter,
        certificate,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> tuple[Event, Job, str | None]:
        protocol = None

        try:
            outcome = self.submission_gateway.submit_event(
                event=saved_event,
                emitter=emitter,
                certificate=certificate,
                certificate_bytes=certificate_bytes,
                certificate_password=certificate_password,
            )
            protocol = outcome.protocol
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
        return updated_event, updated_job, protocol

    def _resolve_emitter_and_active_certificate(self, emitter_id: str):
        emitter = self.emitter_repository.get(emitter_id)
        if emitter is None:
            raise NotFoundError("emitters.not_found")

        certificate = self.certificate_repository.get_active_for_emitter(emitter_id)
        if certificate is None:
            raise ConflictError("certificates.active_required")

        certificate_bytes = self.certificate_store.decrypt_bytes(certificate.encrypted_p12)
        certificate_password = self.certificate_store.decrypt_text(certificate.encrypted_password)
        return emitter, certificate, certificate_bytes, certificate_password

    def _get_document_for_emitter(self, *, emitter_id: str, document_id: str) -> Document:
        document = self.document_repository.get(document_id)
        if document is None or document.emitter_id != emitter_id:
            raise NotFoundError("documents.not_found")
        return document

    def _validate_cancelation(self, *, document: Document) -> None:
        if _is_cancelled_document(document):
            raise ConflictError("events.cancel.already_cancelled")

        if not document.cdc:
            raise ConflictError("events.cancel.document_not_approved")

        document_status = _normalize_status(document.sifen_status or document.internal_status)
        if document_status not in _APPROVED_DOCUMENT_STATUSES:
            raise ConflictError("events.cancel.document_not_approved")

        approved_cancel_events = self.event_repository.list_for_document(
            document_id=document.id,
            event_type=_CANCEL_EVENT_TYPE,
            status="approved",
        )
        if approved_cancel_events:
            raise ConflictError("events.cancel.already_cancelled")

        deadline_hours = _cancel_deadline_hours(document.document_type)
        deadline = document.updated_at + timedelta(hours=deadline_hours)
        now = _now()
        if now > deadline:
            raise ConflictError(
                "events.cancel.deadline_exceeded",
                details={
                    "deadline_hours": deadline_hours,
                    "approved_at": document.updated_at.isoformat(),
                },
            )

        children = self.document_repository.list_by_associated_cdc(
            emitter_id=document.emitter_id,
            associated_cdc=document.cdc,
        )
        pending_children = [
            child.cdc or child.id
            for child in children
            if child.id != document.id and not _is_cancelled_document(child)
        ]
        if pending_children:
            raise ConflictError(
                "events.cancel.child_dte_not_cancelled",
                details={"child_cdcs": pending_children},
            )

    def _validate_inutilization_deadline(
        self,
        *,
        emitter_id: str,
        document_type: str,
        establishment: str,
        point: str,
        numero_hasta: int,
    ) -> None:
        if self.numbering_repository is None:
            return
        current = self.numbering_repository.get_current(
            emitter_id=emitter_id,
            document_type=document_type,
            establishment=establishment,
            point=point,
        )
        if current is None:
            return
        if numero_hasta > current.last_number:
            return
        if _now() - current.updated_at > timedelta(days=45):
            raise ConflictError(
                "events.inutilize.deadline_exceeded",
                details={
                    "sequence_last_number": current.last_number,
                    "sequence_updated_at": current.updated_at.isoformat(),
                },
            )

    def _publish_webhook_event(
        self,
        *,
        emitter_id: str,
        event_type: str,
        payload: dict | None,
    ) -> None:
        if self.webhook_publisher is None:
            return
        try:
            self.webhook_publisher.publish_event(
                emitter_id=emitter_id,
                event_type=event_type,
                payload=payload,
            )
        except Exception:
            logger.exception(
                "event_webhook_publish_failed",
                extra={
                    "emitter_id": emitter_id,
                    "event_type": event_type,
                },
            )


def _now() -> datetime:
    return datetime.now(UTC)


def _normalize_three_digits(value: str) -> str:
    parsed = int(str(value).strip())
    if parsed < 0 or parsed > 999:
        raise UnprocessableEntityError("events.inutilize.invalid_point_or_establishment")
    return f"{parsed:03d}"


def _cancel_deadline_hours(document_type: str) -> int:
    return _CANCEL_DEADLINE_HOURS.get(str(document_type).strip().lower(), 168)


def _normalize_status(status: str | None) -> str:
    return str(status or "").strip().lower()


def _is_cancelled_document(document: Document) -> bool:
    document_status = _normalize_status(document.sifen_status or document.internal_status)
    return document_status in _CANCELLED_DOCUMENT_STATUSES


def _generate_short_numeric_event_id() -> str:
    value = str(uuid4().int % 10_000_000_000)
    if int(value) <= 0:
        return "1"
    return value
