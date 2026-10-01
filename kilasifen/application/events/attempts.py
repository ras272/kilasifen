"""One attempt to submit a fiscal event, split around the SIFEN call.

The worker commits the exact ``rEnviEventoDe`` (event status ``submitting``)
before :func:`send_event_attempt` talks to SIFEN, and records the result in a
second transaction. While SIFEN answers no transaction or row lock is held.

What to do after an uncertain event submission (resend or query first) is a
fiscal decision still pending: today every retry sends the stored signed event
again, as before. The split only guarantees that the attempt, the exact request
and its outcome are durable, and tells a request that never left apart from
an uncertain one.
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
from kilasifen.domain.emitters.models import Emitter
from kilasifen.domain.events.models import Event
from kilasifen.domain.jobs.models import Job
from kilasifen.engine.sdk.errors import SifenError
from kilasifen.infrastructure.sifen.event import (
    EventSubmissionGateway,
    EventSubmissionOutcome,
)

logger = logging.getLogger(__name__)

#: The exact request is persisted and a worker is sending it to SIFEN.
EVENT_SUBMITTING_STATUS = "submitting"

#: How long an attempt may still be waiting on SIFEN after its request was
#: stored. Every SIFEN call runs inside an RQ job, which RQ stops after 180 s
#: by default; the rest is margin.
EVENT_IN_FLIGHT_WINDOW = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class EventAttempt:
    """What the first transaction of an event attempt committed for SIFEN."""

    job_id: str
    event_id: str
    attempt_number: int
    request_xml: str
    emitter: Emitter
    # Kept out of repr so a log line or error report never carries them.
    certificate_bytes: bytes = field(repr=False)
    certificate_password: str = field(repr=False)


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


def _retry(job: Job, *, category: str, message: str) -> Job:
    return replace(
        job,
        status="retry_scheduled",
        error_snapshot={"category": category, "message": message},
        updated_at=_now(),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)
