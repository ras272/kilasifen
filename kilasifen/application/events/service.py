"""Application service layer for fiscal events."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import uuid4

from kilasifen.application.emitters.guards import require_active_emitter
from kilasifen.application.events.attempts import (
    EVENT_SUBMITTING_STATUS,
    DeferredEventJob,
    EventAttempt,
    EventAttemptResult,
    EventPreparationRefused,
    FinishedEventJob,
    in_flight_until,
    send_event_attempt,
)
from kilasifen.application.jobs.service import JobService
from kilasifen.domain.common.errors import (
    ConflictError,
    NotFoundError,
    UnprocessableEntityError,
)
from kilasifen.domain.common.paraguay_time import paraguay_now
from kilasifen.domain.documents.models import Document
from kilasifen.domain.events.inutilized_ranges import InutilizedNumberRange
from kilasifen.domain.events.models import Event
from kilasifen.domain.jobs.models import Job
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.sifen.event import EventSubmissionGateway
from kilasifen.infrastructure.sifen.typed_event_builder import (
    build_signed_cancel_event_group_xml,
    build_signed_inutilization_event_group_xml,
)
from kilasifen.repositories.certificates import CertificateRepository
from kilasifen.repositories.document_numbering_sequences import (
    DocumentNumberingSequenceRepository,
)
from kilasifen.repositories.documents import DocumentRepository
from kilasifen.repositories.emitters import EmitterRepository
from kilasifen.repositories.events import EventRepository
from kilasifen.repositories.inutilized_number_ranges import (
    InutilizedNumberRangeRepository,
)
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
#: Event states that carry SIFEN's final word; a late attempt never moves them.
_SIFEN_FINAL_EVENT_STATUSES = frozenset({"approved", "rejected"})
_MAX_EVENT_ATTEMPTS = 5
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


class EventJobQueue(Protocol):
    """Minimal queue contract used to submit fiscal events asynchronously."""

    def enqueue_event_submit(
        self,
        job: Job,
        *,
        database_url: str,
        encryption_key: str,
    ):
        """Enqueue one durable event job identifier."""


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
        queue: EventJobQueue | None = None,
        database_url: str | None = None,
        encryption_key: str | None = None,
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
        self.queue = queue
        self.database_url = database_url
        self.encryption_key = encryption_key

    def create_event(
        self,
        *,
        emitter_id: str,
        document_id: str,
        event_type: str,
        input_payload: dict | None,
    ) -> tuple[Event, Job]:
        emitter, _certificate, certificate_bytes, certificate_password = (
            self._resolve_emitter_and_active_certificate(emitter_id)
        )

        self._get_document_for_emitter(emitter_id=emitter_id, document_id=document_id)

        event, job, _ = self._create_and_submit_event(
            emitter_id=emitter_id,
            document_id=document_id,
            event_type=event_type,
            input_payload=input_payload,
            emitter=emitter,
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
        emitter, _certificate, certificate_bytes, certificate_password = (
            self._resolve_emitter_and_active_certificate(emitter_id)
        )
        document = self._get_document_for_emitter(
            emitter_id=emitter_id, document_id=document_id
        )
        self._validate_cancelation(document=document)

        event_xml = build_signed_cancel_event_group_xml(
            cdc=document.cdc or "",
            motivo=motivo,
            signed_at=_now_asuncion(),
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
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
        )

        if event.status == "approved":
            self._apply_approved_event(event=event, protocol=None)
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
        emitter, _certificate, certificate_bytes, certificate_password = (
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
            signed_at=_now_asuncion(),
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
            self._apply_approved_event(event=event, protocol=protocol)
        return event, job, saved_range

    def get_event(self, event_id: str) -> tuple[Event, Job | None]:
        event = self.event_repository.get(event_id)
        if event is None:
            raise NotFoundError("events.not_found")
        job = self.job_service.get_for_entity("event", event.id)
        return event, job

    def get_event_for_emitter(
        self, *, emitter_id: str, event_id: str
    ) -> tuple[Event, Job | None]:
        event, job = self.get_event(event_id)
        if event.emitter_id != emitter_id:
            raise NotFoundError("events.not_found")
        return event, job

    def begin_queued_event_attempt(
        self,
        *,
        job_id: str,
        worker_correlation_id: str | None = None,
    ) -> EventAttempt | FinishedEventJob | DeferredEventJob:
        """First transaction of a worker attempt: claim the job, store the request.

        The caller must commit before :func:`send_event_attempt`, so the
        emitter lock taken here is released while SIFEN answers. A refused
        event (bad payload, signature that does not verify) is recorded here
        and nothing is sent. While an earlier attempt may still be at SIFEN
        nothing is claimed either: the caller dispatches the returned
        :class:`DeferredEventJob` again at its ``scheduled_at``.
        """

        job = self.job_service.get_job(job_id)
        if job.related_entity_type != "event" or not job.related_entity_id:
            raise NotFoundError("jobs.event_context_not_found")
        event = self.event_repository.get(job.related_entity_id)
        if event is None:
            raise NotFoundError("events.not_found")
        if _event_job_is_finished(event, job):
            return FinishedEventJob(
                _event_job_payload(event=event, job=job, retryable=False)
            )

        # Lock order shared by every writer: emitter, then event, then job.
        emitter, _certificate, certificate_bytes, certificate_password = (
            self._resolve_emitter_and_active_certificate(event.emitter_id)
        )
        event = _require_row(self.event_repository.get_for_update(event.id))
        job = _require_row(self.job_repository.get_for_update(job.id))
        if _event_job_is_finished(event, job):
            return FinishedEventJob(
                _event_job_payload(event=event, job=job, retryable=False)
            )
        previous_attempt_until = in_flight_until(event)
        if previous_attempt_until is not None:
            return self._defer_attempt(
                event=event, job=job, until=previous_attempt_until
            )

        attempt_number = job.attempts + 1
        job = self.job_repository.save(
            replace(
                job,
                status="processing",
                attempts=attempt_number,
                started_at=job.started_at or _now(),
                worker_correlation_id=worker_correlation_id
                or job.worker_correlation_id,
                updated_at=_now(),
            )
        )
        try:
            event, request_xml = self._store_prepared_submission(
                event=event,
                emitter=emitter,
                certificate_bytes=certificate_bytes,
                certificate_password=certificate_password,
            )
        except SifenValidationError as exc:
            updated_event, updated_job, protocol = EventPreparationRefused(
                str(exc)
            ).apply(event, job)
            return FinishedEventJob(
                self._save_attempt(
                    event=updated_event,
                    job=updated_job,
                    attempt_number=attempt_number,
                    protocol=protocol,
                )
            )
        return EventAttempt(
            job_id=job.id,
            event_id=event.id,
            attempt_number=attempt_number,
            request_xml=request_xml,
            emitter=emitter,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
        )

    def record_event_attempt(
        self,
        *,
        attempt: EventAttempt,
        result: EventAttemptResult,
    ) -> dict[str, str | bool | None]:
        """Second transaction of a worker attempt: record the SIFEN step.

        Event and job are re-read with ``FOR UPDATE``. An event that already
        carries SIFEN's final word is never moved, and a non-final outcome is
        dropped when a newer attempt claimed the job meanwhile.

        Locks follow the order every writer uses: emitter, then event, then
        job. An approved event publishes webhooks, which lock the emitter, and
        taking it last could deadlock with a writer that holds the emitter.
        The emitter wait is not bounded, so SIFEN's answer is never dropped
        over a busy emitter.
        """

        self.emitter_repository.lock_row(attempt.emitter.id)
        event = _require_row(self.event_repository.get_for_update(attempt.event_id))
        job = _require_row(self.job_repository.get_for_update(attempt.job_id))
        updated_event, updated_job, protocol = result.apply(event, job)
        superseded = job.attempts != attempt.attempt_number
        if event.status in _SIFEN_FINAL_EVENT_STATUSES or (
            superseded and updated_event.status not in _SIFEN_FINAL_EVENT_STATUSES
        ):
            logger.warning(
                "events.attempt_outcome_superseded",
                extra={
                    "job_id": job.id,
                    "event_id": event.id,
                    "attempt": attempt.attempt_number,
                    "event_status": event.status,
                },
            )
            return _event_job_payload(event=event, job=job, retryable=False)
        return self._save_attempt(
            event=updated_event,
            job=updated_job,
            attempt_number=attempt.attempt_number,
            protocol=protocol,
        )

    def _defer_attempt(
        self,
        *,
        event: Event,
        job: Job,
        until: datetime,
    ) -> DeferredEventJob:
        """Send nothing while an earlier attempt may still be at SIFEN.

        An operator retry of a job whose worker looks dead, or a duplicate
        dispatch, must not sign and send the event again while the first
        request may still be waiting on SIFEN. The job keeps its status and
        is scheduled for when that window closes.
        """

        job = self.job_repository.save(
            replace(
                job,
                scheduled_at=until,
                error_snapshot={
                    "category": "attempt_in_flight",
                    "message": "a previous attempt may still be waiting on SIFEN",
                },
                updated_at=_now(),
            )
        )
        logger.warning(
            "events.attempt_in_flight",
            extra={
                "job_id": job.id,
                "event_id": event.id,
                "job_status": job.status,
                "retry_at": until.isoformat(),
            },
        )
        return DeferredEventJob(
            job=job,
            payload=_event_job_payload(event=event, job=job, retryable=False),
        )

    def _save_attempt(
        self,
        *,
        event: Event,
        job: Job,
        attempt_number: int,
        protocol: str | None,
    ) -> dict[str, str | bool | None]:
        retryable = job.status == "retry_scheduled"
        if retryable and attempt_number >= _MAX_EVENT_ATTEMPTS:
            retryable = False
            event = replace(
                event,
                status="failed",
                sifen_result_message="event retry attempts exhausted",
                updated_at=_now(),
            )
            job = replace(
                job,
                status="failed",
                error_snapshot={
                    "category": "retry_exhausted",
                    "message": "event retry attempts exhausted",
                },
                finished_at=_now(),
                updated_at=_now(),
            )
        elif job.status in {"succeeded", "failed"}:
            job = replace(job, finished_at=_now(), updated_at=_now())

        self.event_repository.save(event)
        self.job_repository.save(job)
        if event.status == "approved":
            self._apply_approved_event(event=event, protocol=protocol)
        return _event_job_payload(event=event, job=job, retryable=retryable)

    def _store_prepared_submission(
        self,
        *,
        event: Event,
        emitter,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> tuple[Event, str]:
        """Persist the signed event and its exact request as ``submitting``."""

        prepared = self.submission_gateway.prepare_event(
            event=event,
            emitter=emitter,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
        )
        stored = self.event_repository.save(
            replace(
                event,
                signed_xml=prepared.signed_xml,
                sifen_request_xml=prepared.request_xml,
                status=EVENT_SUBMITTING_STATUS,
                updated_at=_now(),
            )
        )
        return stored, prepared.request_xml

    def _create_and_submit_event(
        self,
        *,
        emitter_id: str,
        document_id: str | None,
        event_type: str,
        input_payload: dict | None,
        emitter,
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
        if self.queue is not None:
            if not self.database_url or not self.encryption_key:
                raise RuntimeError("event queue runtime configuration is required")
            self.queue.enqueue_event_submit(
                job,
                database_url=self.database_url,
                encryption_key=self.encryption_key,
            )
            return saved_event, job, None

        updated_event, updated_job, protocol = self._submit_inline(
            event=saved_event,
            job=job,
            emitter=emitter,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
        )
        self.event_repository.save(updated_event)
        self.job_repository.save(updated_job)
        return updated_event, updated_job, protocol

    def _submit_inline(
        self,
        *,
        event: Event,
        job: Job,
        emitter,
        certificate_bytes: bytes,
        certificate_password: str,
    ) -> tuple[Event, Job, str | None]:
        """Submit within the caller's transaction (only without a job queue).

        The API always wires a queue, so requests never reach this path; it
        serves direct uses of the service. The same steps as a worker attempt
        run in a single transaction.
        """

        try:
            event, request_xml = self._store_prepared_submission(
                event=event,
                emitter=emitter,
                certificate_bytes=certificate_bytes,
                certificate_password=certificate_password,
            )
        except SifenValidationError as exc:
            return EventPreparationRefused(str(exc)).apply(event, job)
        attempt = EventAttempt(
            job_id=job.id,
            event_id=event.id,
            attempt_number=job.attempts,
            request_xml=request_xml,
            emitter=emitter,
            certificate_bytes=certificate_bytes,
            certificate_password=certificate_password,
        )
        return send_event_attempt(self.submission_gateway, attempt).apply(event, job)

    def _apply_approved_event(self, *, event: Event, protocol: str | None) -> None:
        if event.event_type == _CANCEL_EVENT_TYPE and event.document_id:
            document = self._get_document_for_emitter(
                emitter_id=event.emitter_id,
                document_id=event.document_id,
            )
            if not _is_cancelled_document(document):
                document = self.document_repository.save(
                    replace(
                        document,
                        internal_status="cancelled",
                        sifen_status="cancelled",
                        updated_at=_now(),
                    )
                )
                self._publish_webhook_event(
                    emitter_id=event.emitter_id,
                    event_type="document.cancelled",
                    payload={
                        "document_id": document.id,
                        "cdc": document.cdc,
                        "event_id": event.id,
                    },
                )
            return

        if event.event_type != _INUTILIZATION_EVENT_TYPE:
            return
        if self.inutilized_range_repository is None:
            raise RuntimeError("inutilized_range_repository is required")
        range_item = self.inutilized_range_repository.get_for_event(event.id)
        if range_item is None:
            raise RuntimeError("inutilized number range was not persisted")
        range_item = self.inutilized_range_repository.save(
            replace(range_item, sifen_protocol=protocol, updated_at=_now())
        )
        self._publish_webhook_event(
            emitter_id=event.emitter_id,
            event_type="numbering.inutilized",
            payload={
                "event_id": event.id,
                "document_type": range_item.document_type,
                "establishment": range_item.establishment,
                "point": range_item.point,
                "numero_desde": range_item.numero_desde,
                "numero_hasta": range_item.numero_hasta,
                "timbrado": range_item.timbrado,
                "sifen_protocol": protocol,
            },
        )

    def _resolve_emitter_and_active_certificate(self, emitter_id: str):
        require_active_emitter(self.emitter_repository, emitter_id)
        emitter = self.emitter_repository.get(emitter_id)
        if emitter is None:
            raise NotFoundError("emitters.not_found")

        certificate = self.certificate_repository.get_active_for_emitter(emitter_id)
        if certificate is None:
            raise ConflictError("certificates.active_required")

        certificate_bytes = self.certificate_store.decrypt_bytes(
            certificate.encrypted_p12
        )
        certificate_password = self.certificate_store.decrypt_text(
            certificate.encrypted_password
        )
        return emitter, certificate, certificate_bytes, certificate_password

    def _get_document_for_emitter(
        self, *, emitter_id: str, document_id: str
    ) -> Document:
        document = self.document_repository.get(document_id)
        if document is None or document.emitter_id != emitter_id:
            raise NotFoundError("documents.not_found")
        return document

    def _validate_cancelation(self, *, document: Document) -> None:
        if _is_cancelled_document(document):
            raise ConflictError("events.cancel.already_cancelled")

        if not document.cdc:
            raise ConflictError("events.cancel.document_not_approved")

        document_status = _normalize_status(
            document.sifen_status or document.internal_status
        )
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
        approved_at = _ensure_utc_datetime(document.updated_at)
        deadline = approved_at + timedelta(hours=deadline_hours)
        now = _now()
        if now > deadline:
            raise ConflictError(
                "events.cancel.deadline_exceeded",
                details={
                    "deadline_hours": deadline_hours,
                    "approved_at": approved_at.isoformat(),
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
        sequence_updated_at = _ensure_utc_datetime(current.updated_at)
        if _now() - sequence_updated_at > timedelta(days=45):
            raise ConflictError(
                "events.inutilize.deadline_exceeded",
                details={
                    "sequence_last_number": current.last_number,
                    "sequence_updated_at": sequence_updated_at.isoformat(),
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
    return datetime.now(timezone.utc)


def _event_job_is_finished(event: Event, job: Job) -> bool:
    if event.status in _SIFEN_FINAL_EVENT_STATUSES:
        return True
    return event.status == "failed" and job.status != "queued"


def _require_row(row):
    if row is None:
        raise NotFoundError("events.not_found")
    return row


def _event_job_payload(
    *,
    event: Event,
    job: Job,
    retryable: bool,
) -> dict[str, str | bool | None]:
    return {
        "job_id": job.id,
        "job_type": job.job_type,
        "event_id": event.id,
        "event_type": event.event_type,
        "job_status": job.status,
        "event_status": event.status,
        "retryable": retryable,
    }


def _now_asuncion() -> datetime:
    # Ley 7354/2024: UTC-03:00 all year, independent of the host tzdata.
    return paraguay_now()


def _ensure_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_three_digits(value: str) -> str:
    parsed = int(str(value).strip())
    if parsed < 0 or parsed > 999:
        raise UnprocessableEntityError(
            "events.inutilize.invalid_point_or_establishment"
        )
    return f"{parsed:03d}"


def _cancel_deadline_hours(document_type: str) -> int:
    return _CANCEL_DEADLINE_HOURS.get(str(document_type).strip().lower(), 168)


def _normalize_status(status: str | None) -> str:
    return str(status or "").strip().lower()


def _is_cancelled_document(document: Document) -> bool:
    document_status = _normalize_status(
        document.sifen_status or document.internal_status
    )
    return document_status in _CANCELLED_DOCUMENT_STATUSES


def _generate_short_numeric_event_id() -> str:
    value = str(uuid4().int % 10_000_000_000)
    if int(value) <= 0:
        return "1"
    return value
