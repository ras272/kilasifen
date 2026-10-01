"""One attempt to submit a fiscal event, split around the SIFEN call.

The worker commits the exact ``rEnviEventoDe`` (event status ``submitting``)
before :func:`run_event_attempt` talks to SIFEN, and records the result in a
second transaction. While SIFEN answers no transaction or row lock is held.

There is no service to query events: the events registered on a CDC come
back from siConsDE in ``rContDe/xContEv`` (MT v150 §8 p. 42, §9.4.3 pp.
51-52). So a cancellation whose earlier attempt may have been registered is
reconciled through the CDC before anything else (DECISIONES F70):

- an attempt that follows an uncertain one queries the CDC first and only
  sends the stored signed event again when no cancellation is registered;
- an answer 4002, 4003, 4009 or 4010 can hide an earlier registration
  (which one SIFEN returns is NO DETERMINADO, MT v150 §11.6.1 p. 134), so the
  CDC is queried before the rejection is believed.

No service tells whether an inutilization was registered (NO DETERMINADO):
an answer 4066 to an attempt that follows an uncertain one is left for an
operator instead of being read as a rejection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Protocol

from kilasifen.application.sifen_submissions import (
    describe_submission_failure,
    request_never_left,
)
from kilasifen.domain.common.sifen_results import (
    CANCELLATION_SUSPECT_CODES,
    INUTILIZATION_OVERLAP_CODE,
)
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.events.models import Event
from kilasifen.domain.jobs.models import Job
from kilasifen.engine.sdk.errors import SifenError
from kilasifen.infrastructure.sifen.event import (
    EventSubmissionGateway,
    EventSubmissionOutcome,
)
from kilasifen.infrastructure.sifen.query import (
    QUERY_FOUND,
    QUERY_NOT_FOUND_OR_NOT_APPROVED,
    DocumentQueryOutcome,
    SifenQueryGateway,
)

logger = logging.getLogger(__name__)

#: The exact request is persisted and a worker is sending it to SIFEN.
EVENT_SUBMITTING_STATUS = "submitting"

#: SIFEN's answer on the event could not be established automatically; an
#: operator retry runs the reconciliation again.
EVENT_RECONCILIATION_REQUIRED_STATUS = "reconciliation_required"

#: Event states after which SIFEN may hold the event although no answer was
#: recorded: the next attempt must not trust a plain resend.
EVENT_UNCERTAIN_STATUSES = frozenset(
    {
        EVENT_SUBMITTING_STATUS,
        "retry_pending",
        EVENT_RECONCILIATION_REQUIRED_STATUS,
    }
)

CANCEL_EVENT_TYPE = "cancel_document"
INUTILIZATION_EVENT_TYPE = "inutilize_numbers"

#: How long an attempt may still be waiting on SIFEN after its request was
#: stored. Every SIFEN call runs inside an RQ job, which RQ stops after 180 s
#: by default; the rest is margin.
EVENT_IN_FLIGHT_WINDOW = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class EventAttempt:
    """What the first transaction of an event attempt committed for SIFEN.

    ``after_uncertain_attempt`` tells that an earlier attempt may have
    reached SIFEN without a recorded answer; ``document_cdc`` is the CDC a
    cancellation is reconciled with.
    """

    job_id: str
    event_id: str
    attempt_number: int
    request_xml: str
    emitter: Emitter
    # Kept out of repr so a log line or error report never carries them.
    certificate_bytes: bytes = field(repr=False)
    certificate_password: str = field(repr=False)
    event_type: str | None = None
    document_cdc: str | None = None
    after_uncertain_attempt: bool = False

    @property
    def is_cancellation(self) -> bool:
        return self.event_type == CANCEL_EVENT_TYPE and bool(self.document_cdc)


@dataclass(frozen=True, slots=True)
class FinishedEventJob:
    """The event job ended without a SIFEN call (already final, or refused)."""

    payload: dict[str, str | bool | None]


@dataclass(frozen=True, slots=True)
class DeferredEventJob:
    """A previous attempt may still be at SIFEN, so nothing is sent now.

    ``job.scheduled_at`` is when no earlier attempt can still be in flight;
    the caller dispatches the job again at that moment.
    """

    job: Job
    payload: dict[str, str | bool | None]


def in_flight_until(event: Event) -> datetime | None:
    """When an earlier attempt of ``event`` can no longer be waiting on SIFEN.

    Only an event left ``submitting`` (request stored, no outcome recorded)
    may still be in flight, and only within :data:`EVENT_IN_FLIGHT_WINDOW`
    of storing its request; ``None`` means no attempt can be in flight.
    """

    if event.status != EVENT_SUBMITTING_STATUS:
        return None
    stored_at = event.updated_at
    if stored_at.tzinfo is None:
        stored_at = stored_at.replace(tzinfo=timezone.utc)
    until = stored_at + EVENT_IN_FLIGHT_WINDOW
    return until if until > _now() else None


class EventAttemptResult(Protocol):
    """Outcome of one attempt, applied to its event and job."""

    def apply(self, event: Event, job: Job) -> tuple[Event, Job, str | None]:
        """Return the event, the job and the SIFEN protocol, if any."""


@dataclass(frozen=True, slots=True)
class EventAnswered:
    """SIFEN answered the submission."""

    outcome: EventSubmissionOutcome

    def apply(self, event: Event, job: Job) -> tuple[Event, Job, str | None]:
        outcome = self.outcome
        updated_event = replace(
            event,
            sifen_response_raw=outcome.response_raw,
            status=outcome.status,
            sifen_result_code=outcome.result_code,
            sifen_result_message=outcome.result_message,
            updated_at=_now(),
        )
        if outcome.status == "rejected":
            updated_job = replace(
                job,
                status="failed",
                error_snapshot={
                    "category": "sifen_rejection",
                    "code": outcome.result_code,
                    "message": outcome.result_message or "event rejected by sifen",
                },
                updated_at=_now(),
            )
        elif outcome.status == "approved":
            updated_job = replace(
                job, status="succeeded", error_snapshot=None, updated_at=_now()
            )
        else:
            updated_job = replace(
                job,
                status="retry_scheduled",
                error_snapshot={
                    "category": "sifen_pending",
                    "code": outcome.result_code,
                    "message": outcome.result_message,
                },
                updated_at=_now(),
            )
        return updated_event, updated_job, outcome.protocol


@dataclass(frozen=True, slots=True)
class EventFoundRegistered:
    """siConsDE shows the cancellation registered on the CDC (xContEv)."""

    query: DocumentQueryOutcome
    protocol: str | None
    answer: EventSubmissionOutcome | None = None

    def apply(self, event: Event, job: Job) -> tuple[Event, Job, str | None]:
        updated_event = replace(
            event,
            status="approved",
            sifen_response_raw=(
                self.answer.response_raw if self.answer else event.sifen_response_raw
            ),
            sifen_result_code=self.query.result_code,
            sifen_result_message=(
                "cancellation registered at SIFEN (found in siConsDE xContEv)"
            ),
            updated_at=_now(),
        )
        updated_job = replace(
            job, status="succeeded", error_snapshot=None, updated_at=_now()
        )
        return updated_event, updated_job, self.protocol


@dataclass(frozen=True, slots=True)
class EventUnresolved:
    """SIFEN's answer on the event cannot be established automatically."""

    message: str
    query: DocumentQueryOutcome | None = None
    answer: EventSubmissionOutcome | None = None

    def apply(self, event: Event, job: Job) -> tuple[Event, Job, str | None]:
        code = self.answer.result_code if self.answer else None
        if code is None and self.query is not None:
            code = self.query.result_code
        updated_event = replace(
            event,
            status=EVENT_RECONCILIATION_REQUIRED_STATUS,
            sifen_response_raw=(
                self.answer.response_raw if self.answer else event.sifen_response_raw
            ),
            sifen_result_code=code,
            sifen_result_message=self.message,
            updated_at=_now(),
        )
        updated_job = replace(
            job,
            status="failed",
            error_snapshot={
                "category": "reconciliation_required",
                "code": code,
                "message": self.message,
            },
            updated_at=_now(),
        )
        return updated_event, updated_job, None


@dataclass(frozen=True, slots=True)
class EventReconciliationUnavailable:
    """The CDC could not be queried; nothing more was sent, it is tried later.

    ``answer`` is a suspicious rejection still waiting for that query.
    """

    message: str
    query: DocumentQueryOutcome | None = None
    answer: EventSubmissionOutcome | None = None

    def apply(self, event: Event, job: Job) -> tuple[Event, Job, str | None]:
        updated = replace(
            event,
            status="retry_pending",
            sifen_result_message=self.message,
            updated_at=_now(),
        )
        if self.answer is not None:
            updated = replace(
                updated,
                sifen_response_raw=self.answer.response_raw,
                sifen_result_code=self.answer.result_code,
            )
        return (
            updated,
            _retry(job, category="reconciliation_unavailable", message=self.message),
            None,
        )


@dataclass(frozen=True, slots=True)
class EventRequestNotSent:
    """The request provably never reached SIFEN."""

    message: str

    def apply(self, event: Event, job: Job) -> tuple[Event, Job, str | None]:
        return (
            replace(
                event,
                status="queued",
                sifen_result_message=self.message,
                updated_at=_now(),
            ),
            _retry(job, category="transport_not_sent", message=self.message),
            None,
        )


@dataclass(frozen=True, slots=True)
class EventOutcomeUnknown:
    """The request may have reached SIFEN, but no readable answer came back."""

    message: str

    def apply(self, event: Event, job: Job) -> tuple[Event, Job, str | None]:
        return (
            replace(
                event,
                status="retry_pending",
                sifen_result_message=self.message,
                updated_at=_now(),
            ),
            _retry(job, category="transport", message=self.message),
            None,
        )


@dataclass(frozen=True, slots=True)
class EventPreparationRefused:
    """The event could not be wrapped or verified; nothing was sent."""

    message: str

    def apply(self, event: Event, job: Job) -> tuple[Event, Job, str | None]:
        return (
            replace(
                event,
                status="failed",
                sifen_result_message=self.message,
                updated_at=_now(),
            ),
            replace(
                job,
                status="failed",
                error_snapshot={
                    "category": "fiscal_validation",
                    "message": self.message,
                },
                updated_at=_now(),
            ),
            None,
        )


def run_event_attempt(
    gateway: EventSubmissionGateway,
    query_gateway: SifenQueryGateway | None,
    attempt: EventAttempt,
) -> EventAttemptResult:
    """Run the SIFEN step of one attempt; every failure becomes a result.

    A cancellation is reconciled through its CDC before a resend that
    follows an uncertain attempt and before a suspicious rejection is
    believed (DECISIONES F70).
    """

    if attempt.is_cancellation and attempt.after_uncertain_attempt:
        settled = _registered_cancellation(query_gateway, attempt, answer=None)
        if settled is not None:
            return settled

    result = send_event_attempt(gateway, attempt)
    if not isinstance(result, EventAnswered) or result.outcome.status != "rejected":
        return result
    code = result.outcome.result_code
    if attempt.is_cancellation and code in CANCELLATION_SUSPECT_CODES:
        settled = _registered_cancellation(
            query_gateway, attempt, answer=result.outcome
        )
        return settled if settled is not None else result
    if (
        attempt.event_type == INUTILIZATION_EVENT_TYPE
        and attempt.after_uncertain_attempt
        and code == INUTILIZATION_OVERLAP_CODE
    ):
        return EventUnresolved(
            message=(
                "SIFEN answered 4066 after an uncertain attempt: the range may "
                "be inutilized by that attempt or overlap another one; no "
                "service tells which (NO DETERMINADO)"
            ),
            answer=result.outcome,
        )
    return result


def send_event_attempt(
    gateway: EventSubmissionGateway,
    attempt: EventAttempt,
) -> EventAttemptResult:
    """Send the stored request; every failure becomes a result, none escapes."""

    try:
        outcome = gateway.submit_prepared(
            request_xml=attempt.request_xml,
            emitter=attempt.emitter,
            certificate_bytes=attempt.certificate_bytes,
            certificate_password=attempt.certificate_password,
        )
    except Exception as exc:  # every failure is recorded by the second transaction
        message = describe_submission_failure(exc)
        never_left = request_never_left(exc)
        logger.warning(
            "events.request_not_sent" if never_left else "events.outcome_unknown",
            extra={
                "job_id": attempt.job_id,
                "event_id": attempt.event_id,
                "attempt": attempt.attempt_number,
                "error_type": type(exc).__name__,
            },
            exc_info=not isinstance(exc, SifenError),
        )
        if never_left:
            return EventRequestNotSent(message)
        return EventOutcomeUnknown(message)
    return EventAnswered(outcome)


def _registered_cancellation(
    query_gateway: SifenQueryGateway | None,
    attempt: EventAttempt,
    *,
    answer: EventSubmissionOutcome | None,
) -> EventAttemptResult | None:
    """Query the CDC and settle the cancellation, if its answer allows.

    Returns ``None`` when SIFEN holds the DTE without a cancellation: the
    stored event may be sent (``answer is None``) or the rejection believed.
    """

    if query_gateway is None:
        return EventUnresolved(
            message="no CDC query available to confirm the cancellation",
            answer=answer,
        )
    cdc = attempt.document_cdc or ""
    try:
        query = query_gateway.query_document(
            emitter=attempt.emitter,
            certificate_bytes=attempt.certificate_bytes,
            certificate_password=attempt.certificate_password,
            cdc=cdc,
        )
    except Exception as exc:  # recorded by the second transaction
        logger.warning(
            "events.reconciliation_unavailable",
            extra={
                "job_id": attempt.job_id,
                "event_id": attempt.event_id,
                "attempt": attempt.attempt_number,
                "error_type": type(exc).__name__,
            },
            exc_info=not isinstance(exc, SifenError),
        )
        return EventReconciliationUnavailable(
            describe_submission_failure(exc), answer=answer
        )

    if query.status == QUERY_FOUND:
        registered = (
            query.container.cancellation_for(cdc) if query.container else None
        )
        if registered is not None:
            return EventFoundRegistered(
                query=query,
                protocol=registered.protocol,
                answer=answer,
            )
        return None
    if query.status == QUERY_NOT_FOUND_OR_NOT_APPROVED:
        # Whether a cancelled DTE answers 0420 or 0422 is NO DETERMINADO.
        return EventUnresolved(
            message=(
                "SIFEN answered 0420 for the CDC of an approved document: it may "
                "already be cancelled (NO DETERMINADO); nothing was sent"
            ),
            query=query,
            answer=answer,
        )
    return EventReconciliationUnavailable(
        message=f"the CDC query answered {query.result_code}; it is tried again",
        query=query,
        answer=answer,
    )


def _retry(job: Job, *, category: str, message: str) -> Job:
    return replace(
        job,
        status="retry_scheduled",
        error_snapshot={"category": category, "message": message},
        updated_at=_now(),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
