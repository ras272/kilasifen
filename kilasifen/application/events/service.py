"""Application service layer for fiscal events."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo

from kilasifen.application.emitters.guards import require_active_emitter
from kilasifen.application.events.attempts import (
    CANCEL_EVENT_TYPE,
    EVENT_RECONCILIATION_REQUIRED_STATUS,
    EVENT_SUBMITTING_STATUS,
    EVENT_UNCERTAIN_STATUSES,
    INUTILIZATION_EVENT_TYPE,
    DeferredEventJob,
    EventAttempt,
    EventAttemptResult,
    EventPreparationRefused,
    FinishedEventJob,
    in_flight_until,
    run_event_attempt,
)
from kilasifen.application.jobs.service import JobService
from kilasifen.domain.common.errors import (
    ConflictError,
    NotFoundError,
    UnprocessableEntityError,
)
from kilasifen.domain.common.fiscal_states import (
    DOCUMENT_APPROVED_STATUSES,
    DOCUMENT_INUTILIZED_STATUS,
    DOCUMENT_POSSIBLY_RECEIVED_STATUSES,
)
from kilasifen.domain.documents.models import Document
from kilasifen.domain.events.inutilization import (
    ACTIVE_JOB_STATUSES,
    inutilization_deadline,
    is_inutilizable,
)
from kilasifen.domain.events.inutilized_ranges import InutilizedNumberRange
from kilasifen.domain.events.models import Event
from kilasifen.domain.jobs.models import Job
from kilasifen.engine.sdk.errors import SifenValidationError
from kilasifen.infrastructure.crypto.certificate_store import EncryptedCertificateStore
from kilasifen.infrastructure.sifen.de_facts import (
    PARAGUAY_TZ,
    approval_lower_bound,
    paraguay_today,
    read_de_facts,
)
from kilasifen.infrastructure.sifen.event import EventSubmissionGateway
from kilasifen.infrastructure.sifen.query import (
    DocumentQueryOutcome,
    SifenQueryGateway,
)
from kilasifen.infrastructure.sifen.typed_event_builder import (
    build_signed_cancel_event_group_xml,
    build_signed_inutilization_event_group_xml,
)
from kilasifen.repositories.certificates import CertificateRepository
from kilasifen.repositories.documents import DocumentRepository
from kilasifen.repositories.emitters import EmitterRepository
from kilasifen.repositories.events import EventRepository
from kilasifen.repositories.inutilized_number_ranges import (
    InutilizedNumberRangeRepository,
)
from kilasifen.repositories.jobs import JobRepository
from kilasifen.repositories.stampings import StampingRepository

logger = logging.getLogger(__name__)

_CANCEL_EVENT_TYPE = CANCEL_EVENT_TYPE
_INUTILIZATION_EVENT_TYPE = INUTILIZATION_EVENT_TYPE

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

#: Cancellation deadline counted from the approval in SIFEN: 48 h for a FE,
#: 168 h for the other DTE (MT v150 §6.2.1 p. 25; §11.6.1 4009/4010 p. 134;
#: RG 23/2019 Art. 22).
_CANCEL_DEADLINE_HOURS = {
    "factura": 48,
    "nota_credito": 168,
    "nota_debito": 168,
    "nota_remision": 168,
    "autofactura": 168,
}

_APPROVED_DOCUMENT_STATUSES = DOCUMENT_APPROVED_STATUSES
#: Cancellation events that may still be registered: a second one would be
#: rejected as a duplicate (4003, MT v150 §11.6.1 p. 134).
_PENDING_EVENT_STATUSES = frozenset({"queued", *EVENT_UNCERTAIN_STATUSES})
#: Associated documents that are, or may become, DTE before the parent is
#: cancelled (MT v150 Tabla J p. 117; Dto 872/2023 Arts. 30 and 40).
_IN_FLIGHT_DOCUMENT_STATUSES = frozenset(
    {"processing", *DOCUMENT_POSSIBLY_RECEIVED_STATUSES}
)
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
        inutilized_range_repository: InutilizedNumberRangeRepository | None = None,
        stamping_repository: StampingRepository | None = None,
        webhook_publisher: WebhookPublisher | None = None,
        queue: EventJobQueue | None = None,
        database_url: str | None = None,
        encryption_key: str | None = None,
        query_gateway: SifenQueryGateway | None = None,
    ):
        self.event_repository = event_repository
        self.emitter_repository = emitter_repository
        self.document_repository = document_repository
        self.certificate_repository = certificate_repository
        self.job_repository = job_repository
        self.job_service = JobService(job_repository)
        self.certificate_store = certificate_store
        self.submission_gateway = submission_gateway
        self.inutilized_range_repository = inutilized_range_repository
        self.stamping_repository = stamping_repository
        self.webhook_publisher = webhook_publisher
        self.queue = queue
        self.database_url = database_url
        self.encryption_key = encryption_key
        self.query_gateway = query_gateway

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
        serie: str | None = None,
    ) -> tuple[Event, Job, InutilizedNumberRange, list[str]]:
        """Inutilize a range of numbers of one timbrado (DECISIONES F72).

        Returns the event, its job, the range and the warnings (today only
        ``inutilization.extemporaneous``: past day 15 of the month after
        the earliest number in the range was consumed; SIFEN has no
        rejection for it, so it is never refused).
        """

        emitter, _certificate, certificate_bytes, certificate_password = (
            self._resolve_emitter_and_active_certificate(emitter_id)
        )
        if self.inutilized_range_repository is None:
            raise RuntimeError("inutilized_range_repository is required")
        normalized_timbrado = str(timbrado).strip()
        self._require_emitter_timbrado(emitter_id, normalized_timbrado)

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

        numbered = [
            document
            for document in self.document_repository.list_in_number_range(
                emitter_id=emitter_id,
                document_type=normalized_document_type,
                establishment=normalized_est,
                point=normalized_point,
                number_from=numero_desde,
                number_to=numero_hasta,
                timbrado=normalized_timbrado,
            )
            if _numbered_under(document, normalized_timbrado)
        ]
        blocking = [
            document for document in numbered if not self._is_inutilizable(document)
        ]
        if blocking:
            raise ConflictError(
                "events.inutilize.range_already_used",
                details={
                    "collisions": [document.document_number for document in blocking],
                    "documents": [
                        {
                            "document_id": document.id,
                            "numero": document.document_number,
                            "status": document.internal_status,
                        }
                        for document in blocking
                    ],
                },
            )

        overlapping_ranges = self.inutilized_range_repository.list_overlapping(
            emitter_id=emitter_id,
            document_type=normalized_document_type,
            establishment=normalized_est,
            point=normalized_point,
            number_from=numero_desde,
            number_to=numero_hasta,
            approved_only=True,
            timbrado=normalized_timbrado,
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

        deadline = _range_deadline(numbered)
        extemporaneous = deadline is not None and paraguay_today() > deadline
        event_xml = build_signed_inutilization_event_group_xml(
            timbrado=normalized_timbrado,
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
            serie=serie,
        )
        payload = {
            "event_xml": event_xml,
            "typed_contract": {
                "contract": "inutilize_numbers_v1",
                "payload": {
                    "timbrado": normalized_timbrado,
                    "document_type": normalized_document_type,
                    "establishment": normalized_est,
                    "point": normalized_point,
                    "numero_desde": numero_desde,
                    "numero_hasta": numero_hasta,
                    "motivo": motivo,
                    "i_tide": i_tide,
                    "serie": serie,
                    "document_ids": [document.id for document in numbered],
                    "deadline": deadline.isoformat() if deadline else None,
                    "extemporaneous": extemporaneous,
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
            timbrado=normalized_timbrado,
            event_id=event.id,
            sifen_protocol=protocol if event.status == "approved" else None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        saved_range = self.inutilized_range_repository.save(range_item)

        if event.status == "approved":
            self._apply_approved_event(event=event, protocol=protocol)
        warnings = []
        if extemporaneous:
            warnings.append("inutilization.extemporaneous")
            logger.warning(
                "events.inutilize.extemporaneous",
                extra={
                    "event_id": event.id,
                    "emitter_id": emitter_id,
                    "deadline": deadline.isoformat() if deadline else None,
                },
            )
        return event, job, saved_range, warnings

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
        # An earlier attempt may have reached SIFEN without a recorded answer:
        # a cancellation is then reconciled by CDC before it is sent again.
        after_uncertain_attempt = event.status in EVENT_UNCERTAIN_STATUSES

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
            event_type=event.event_type,
            document_cdc=self._event_document_cdc(event),
            after_uncertain_attempt=after_uncertain_attempt,
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
        query = getattr(result, "query", None)
        if query is not None:
            self._trace_document_query(event=updated_event, query=query)
        return self._save_attempt(
            event=updated_event,
            job=updated_job,
            attempt_number=attempt.attempt_number,
            protocol=protocol,
        )

    def _event_document_cdc(self, event: Event) -> str | None:
        if not event.document_id:
            return None
        document = self.document_repository.get(event.document_id)
        return document.cdc if document is not None else None

    def _trace_document_query(
        self,
        *,
        event: Event,
        query: DocumentQueryOutcome,
    ) -> None:
        """Keep the siConsDE that reconciled ``event`` on its document."""

        if not event.document_id:
            return
        document = self.document_repository.get(event.document_id)
        if document is None:
            return
        self.document_repository.save(
            replace(
                document,
                last_query_request_xml=query.request_xml,
                last_query_response_raw=query.response_raw,
                last_query_at=_now(),
                updated_at=_now(),
            )
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
            # An event whose last attempt may have reached SIFEN is left for
            # an operator, who retries it after a reconciliation; one that
            # never left fails.
            uncertain = event.status in EVENT_UNCERTAIN_STATUSES
            event = replace(
                event,
                status=EVENT_RECONCILIATION_REQUIRED_STATUS if uncertain else "failed",
                sifen_result_message="event retry attempts exhausted",
                updated_at=_now(),
            )
            job = replace(
                job,
                status="failed",
                error_snapshot={
                    "category": (
                        "reconciliation_required" if uncertain else "retry_exhausted"
                    ),
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
            event_type=event.event_type,
            document_cdc=self._event_document_cdc(event),
        )
        return run_event_attempt(
            self.submission_gateway, self.query_gateway, attempt
        ).apply(event, job)

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
        inutilized = self._mark_documents_inutilized(range_item)
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
                "document_ids": [document.id for document in inutilized],
            },
        )

    def _mark_documents_inutilized(
        self, range_item: InutilizedNumberRange
    ) -> list[Document]:
        """Move the documents of an inutilized range to ``inutilized``.

        Only those still inutilizable: one sent again meanwhile is left to
        its job and logged, since SIFEN will reject it with 1109 (MT v150
        §12.4 C007 p. 161). 1109 applies per timbrado, so a document signed
        under another timbrado is never marked (:func:`_numbered_under`).
        """

        marked: list[Document] = []
        for document in self.document_repository.list_in_number_range(
            emitter_id=range_item.emitter_id,
            document_type=range_item.document_type,
            establishment=range_item.establishment,
            point=range_item.point,
            number_from=range_item.numero_desde,
            number_to=range_item.numero_hasta,
            timbrado=range_item.timbrado,
        ):
            if not _numbered_under(document, range_item.timbrado):
                continue
            if not self._is_inutilizable(document):
                logger.warning(
                    "events.inutilize.document_changed",
                    extra={
                        "document_id": document.id,
                        "document_status": document.internal_status,
                        "event_id": range_item.event_id,
                    },
                )
                continue
            marked.append(
                self.document_repository.save(
                    replace(
                        document,
                        internal_status=DOCUMENT_INUTILIZED_STATUS,
                        sifen_status=DOCUMENT_INUTILIZED_STATUS,
                        updated_at=_now(),
                    )
                )
            )
        return marked

    def _is_inutilizable(self, document: Document) -> bool:
        return is_inutilizable(document.internal_status, self._job_status(document))

    def _blocks_parent_cancellation(self, child: Document) -> bool:
        """A child DTE, one that may be at SIFEN, or one about to travel.

        A child that already holds its signed DE and CDC while its job can
        still send it (the same DE after a 0420, a request that never left,
        a rejection 0161/0162 sent again) may become a DTE before the
        parent is cancelled: Tabla J asks to cancel the associated DTE first
        and SIFEN rejects a DE whose associated DTE is cancelled (2404, MT
        v150 H004b). Rejected, locally failed, cancelled, inutilized and
        queued children that will not travel, or were never built, do not
        block (MT v150 Tabla J p. 117; Dto 872/2023 Arts. 30 and 40;
        DECISIONES F71).
        """

        status = _normalize_status(child.internal_status)
        if (
            status in _APPROVED_DOCUMENT_STATUSES
            or status in _IN_FLIGHT_DOCUMENT_STATUSES
        ):
            return True
        if not (child.signed_xml and child.cdc):
            return False
        return self._job_status(child) in ACTIVE_JOB_STATUSES

    def _job_status(self, document: Document) -> str | None:
        job = self.job_repository.get_for_entity("document", document.id)
        return job.status if job is not None else None

    def _require_emitter_timbrado(self, emitter_id: str, timbrado: str) -> None:
        """The timbrado must belong to the emitter (4052, MT v150 §11.6.2)."""

        if self.stamping_repository is None:
            raise RuntimeError("stamping_repository is required")
        numbers = {
            stamping.number
            for stamping in self.stamping_repository.list_for_emitter(emitter_id)
        }
        if timbrado not in numbers:
            raise UnprocessableEntityError("events.inutilize.unknown_timbrado")

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

        cancel_events = self.event_repository.list_for_document(
            document_id=document.id,
            event_type=_CANCEL_EVENT_TYPE,
        )
        if any(event.status == "approved" for event in cancel_events):
            raise ConflictError("events.cancel.already_cancelled")
        pending = [
            event.id for event in cancel_events if _cancellation_may_register(event)
        ]
        if pending:
            # DECISIONES F70: a second request would be a duplicate (4003).
            raise ConflictError(
                "events.cancel.already_pending",
                details={"event_ids": pending},
            )

        self._validate_cancellation_deadline(document)

        children = self.document_repository.list_by_associated_cdc(
            emitter_id=document.emitter_id,
            associated_cdc=document.cdc,
        )
        blocking_children = [
            child.cdc or child.id
            for child in children
            if child.id != document.id and self._blocks_parent_cancellation(child)
        ]
        if blocking_children:
            raise ConflictError(
                "events.cancel.child_dte_not_cancelled",
                details={"child_cdcs": blocking_children},
            )

    def _validate_cancellation_deadline(self, document: Document) -> None:
        """48 h (FE) or 168 h (other DTE) from the approval in SIFEN.

        DECISIONES F71: anchored on ``sifen_approved_at`` (``dFecProc``), or
        on a lower bound of the approval when SIFEN's time is unknown, so the
        local window never outlives SIFEN's (4009/4010, MT v150 §11.6.1
        p. 134). Once it passes, the DTE is annulled with a credit note (RG
        23/2019 Art. 22).
        """

        deadline_hours = _cancel_deadline_hours(document.document_type)
        if document.sifen_approved_at is not None:
            approved_at = _ensure_utc_datetime(document.sifen_approved_at)
            source = "sifen"
        else:
            approved_at = approval_lower_bound(document)
            source = "lower_bound"
        if _now() > approved_at + timedelta(hours=deadline_hours):
            raise ConflictError(
                "events.cancel.deadline_exceeded",
                details={
                    "deadline_hours": deadline_hours,
                    "approved_at": approved_at.isoformat(),
                    "approved_at_source": source,
                    "remedy": "nota_credito",
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
    if event.status in {"failed", EVENT_RECONCILIATION_REQUIRED_STATUS}:
        # Only an operator retry (a queued job) runs it again.
        return job.status != "queued"
    return False


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
    return datetime.now(ZoneInfo("America/Asuncion"))


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


def _range_deadline(documents: list[Document]) -> date | None:
    """Deadline of the earliest number of the range that has a document.

    A number without document carries no consumption date: no deadline is
    computed for it (the platform reserves numbers with their document).
    """

    if not documents:
        return None
    consumed_on = min(
        _ensure_utc_datetime(document.created_at).astimezone(PARAGUAY_TZ).date()
        for document in documents
    )
    return inutilization_deadline(consumed_on)


def _cancel_deadline_hours(document_type: str) -> int:
    return _CANCEL_DEADLINE_HOURS.get(str(document_type).strip().lower(), 168)


def _normalize_status(status: str | None) -> str:
    return str(status or "").strip().lower()


def _is_cancelled_document(document: Document) -> bool:
    document_status = _normalize_status(
        document.sifen_status or document.internal_status
    )
    return document_status in _CANCELLED_DOCUMENT_STATUSES


def _cancellation_may_register(event: Event) -> bool:
    """A cancellation not final yet, or failed after its request was stored."""

    if event.status in _PENDING_EVENT_STATUSES:
        return True
    return event.status == "failed" and bool(event.sifen_request_xml)


def _numbered_under(document: Document, timbrado: str) -> bool:
    """Whether the number of ``document`` belongs to ``timbrado``.

    A number is inutilized per timbrado, establishment and point (1109, MT
    v150 §12.4 C007 p. 161). Without a recorded timbrado the ``dNumTim``
    (C004) of its XML decides; a document never built carries none and
    counts for the range the operator inutilized.
    """

    if document.timbrado is not None:
        return document.timbrado == timbrado
    found = read_de_facts(document.signed_xml or document.generated_xml).timbrado
    return found is None or found == timbrado


def _generate_short_numeric_event_id() -> str:
    value = str(uuid4().int % 10_000_000_000)
    if int(value) <= 0:
        return "1"
    return value
