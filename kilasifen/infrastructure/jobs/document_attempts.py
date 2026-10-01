"""State rules for one attempt of a ``document.emit`` job.

An attempt runs in three steps and never holds a database transaction or a
row lock while it waits on SIFEN:

1. A first transaction claims the job (``processing``, one more attempt) and,
   when the document is going to be sent, stores the generated and signed XML,
   the exact ``rEnviDe`` request and the CDC, marking the document
   ``submitting``. Then it commits.
2. The SIFEN call (send the request, or query the CDC) runs on its own.
3. A second transaction re-reads document and job with ``FOR UPDATE`` and
   records the result of step 2.

This module holds the pure rules of steps 1 and 3; the worker owns sessions
and I/O. A document that may already be at SIFEN is only ever queried by CDC.
A document whose request provably never left goes back to ``queued`` and its
persisted request is sent again, unchanged, on the next attempt.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Protocol

from kilasifen.domain.common.fiscal_states import (
    DOCUMENT_POSSIBLY_RECEIVED_STATUSES,
    DOCUMENT_SUBMITTING_STATUS,
    DOCUMENT_TERMINAL_STATUSES,
    job_status_for_document,
)
from kilasifen.domain.documents.models import Document
from kilasifen.domain.jobs.models import Job
from kilasifen.infrastructure.sifen.engine import PreparedSubmission, SubmissionOutcome
from kilasifen.infrastructure.sifen.query import DocumentQueryOutcome

MAX_DOCUMENT_ATTEMPTS = 5
DOCUMENT_RETRY_DELAYS = (30, 120, 600, 1800)

_RECONCILIATION_REQUIRED_MESSAGE = (
    "automatic reconciliation attempts exhausted; "
    "the immutable CDC was not resubmitted"
)
_NEVER_DELIVERED_MESSAGE = (
    "SIFEN could not be reached; the prepared request was never delivered "
    "and a manual retry sends it unchanged"
)


class AttemptAction(str, Enum):
    """What one attempt does with its document."""

    PREPARE = "prepare"
    """Build and sign the document, persist the request, send it."""

    RESEND = "resend"
    """Send again the persisted request of an attempt that never left."""

    RECONCILE = "reconcile"
    """Query the CDC; the document may already be at SIFEN."""


def select_action(document: Document) -> AttemptAction:
    """Decide what the next attempt does with ``document``."""

    if document.internal_status in DOCUMENT_POSSIBLY_RECEIVED_STATUSES and document.cdc:
        return AttemptAction.RECONCILE
    if document.internal_status == "queued" and _has_prepared_request(document):
        return AttemptAction.RESEND
    return AttemptAction.PREPARE


def is_finished(document: Document, job: Job) -> bool:
    """Tell whether the job has nothing left to do.

    A ``failed`` document whose job was queued again by an operator is the
    one terminal state that still runs.
    """

    if document.internal_status not in DOCUMENT_TERMINAL_STATUSES:
        return False
    return not (document.internal_status == "failed" and job.status == "queued")


def start_attempt(job: Job, *, worker_correlation_id: str | None) -> Job:
    """Claim the job for one more attempt."""

    now = _now()
    return replace(
        job,
        status="processing",
        attempts=job.attempts + 1,
        started_at=now,
        finished_at=None,
        worker_correlation_id=worker_correlation_id,
        updated_at=now,
    )


def mark_submitting(
    document: Document,
    prepared: PreparedSubmission | None = None,
) -> Document:
    """Persist what is about to be sent; ``prepared`` is ``None`` on a resend."""

    if prepared is not None:
        document = replace(
            document,
            generated_xml=prepared.generated_xml,
            signed_xml=prepared.signed_xml,
            sifen_request_xml=prepared.request_xml,
            cdc=prepared.cdc,
        )
    return replace(
        document,
        internal_status=DOCUMENT_SUBMITTING_STATUS,
        updated_at=_now(),
    )


class AttemptResult(Protocol):
    """Outcome of one attempt, applied to the document and job it belongs to."""

    def apply(self, document: Document, job: Job) -> tuple[Document, Job]:
        """Return the document and job that record this outcome."""


@dataclass(frozen=True, slots=True)
class SifenAnswered:
    """SIFEN answered the submission."""

    outcome: SubmissionOutcome

    def apply(self, document: Document, job: Job) -> tuple[Document, Job]:
        updated = replace(
            document,
            sifen_response_raw=self.outcome.response_raw,
            internal_status=self.outcome.sifen_status,
            sifen_status=self.outcome.sifen_status,
            sifen_result_code=self.outcome.result_code,
            sifen_result_message=self.outcome.result_message,
            updated_at=_now(),
        )
        return updated, _job_following(job, updated, pending_category="sifen_pending")


@dataclass(frozen=True, slots=True)
class SifenRejected:
    """The transport reported a functional rejection from SIFEN."""

    code: str
    message: str

    def apply(self, document: Document, job: Job) -> tuple[Document, Job]:
        updated = replace(
            document,
            internal_status="rejected",
            sifen_status="rejected",
            sifen_result_code=self.code,
            sifen_result_message=self.message,
            updated_at=_now(),
        )
        return updated, _job_following(job, updated, pending_category="sifen_pending")


@dataclass(frozen=True, slots=True)
class RequestNotSent:
    """The request provably never reached SIFEN; it is kept for a resend."""

    message: str

    def apply(self, document: Document, job: Job) -> tuple[Document, Job]:
        updated = replace(document, internal_status="queued", updated_at=_now())
        return updated, _retry(job, category="transport_not_sent", message=self.message)


@dataclass(frozen=True, slots=True)
class OutcomeUnknown:
    """The request may have reached SIFEN, but no readable answer came back."""

    message: str

    def apply(self, document: Document, job: Job) -> tuple[Document, Job]:
        updated = replace(
            document,
            internal_status="retry_pending",
            sifen_status="retry_pending",
            sifen_result_message=self.message,
            updated_at=_now(),
        )
        return updated, _retry(job, category="transport", message=self.message)


@dataclass(frozen=True, slots=True)
class PreparationRefused:
    """The document could not be built or signed; nothing was sent."""

    message: str

    def apply(self, document: Document, job: Job) -> tuple[Document, Job]:
        updated = replace(document, internal_status="failed", updated_at=_now())
        return updated, _fail(job, category="fiscal_validation", message=self.message)


@dataclass(frozen=True, slots=True)
class Reconciled:
    """SIFEN answered the query by CDC."""

    outcome: DocumentQueryOutcome

    def apply(self, document: Document, job: Job) -> tuple[Document, Job]:
        traced = replace(
            document,
            last_query_request_xml=self.outcome.request_xml,
            last_query_response_raw=self.outcome.response_raw,
            last_query_at=_now(),
            sifen_result_code=self.outcome.result_code,
            sifen_result_message=self.outcome.result_message,
            updated_at=_now(),
        )
        if self.outcome.status != "found":
            # SIFEN code 0420 combines "not found" and "not approved". It is not
            # proof that the previous submission failed, so resending here could
            # duplicate one fiscal intent. Keep querying the immutable CDC.
            pending = replace(
                traced,
                internal_status="retry_pending",
                sifen_status="retry_pending",
            )
            return pending, _job_following(
                job, pending, pending_category="reconciliation_pending"
            )

        signed_xml = self.outcome.content_xml or document.signed_xml
        if not signed_xml:
            return _still_pending(traced), _fail(
                job,
                category="fiscal_validation",
                message="SIFEN returned a document without XML content",
            )
        approved = replace(
            traced,
            signed_xml=signed_xml,
            internal_status="approved",
            sifen_status="approved",
        )
        return approved, _succeed(job)


@dataclass(frozen=True, slots=True)
class ReconciliationUnavailable:
    """The query by CDC failed in transport; it is tried again later."""

    message: str

    def apply(self, document: Document, job: Job) -> tuple[Document, Job]:
        updated = replace(document, internal_status="retry_pending", updated_at=_now())
        return updated, _retry(job, category="transport", message=self.message)


@dataclass(frozen=True, slots=True)
class ReconciliationRefused:
    """The query by CDC was refused before reaching SIFEN (configuration).

    The document may be at SIFEN, so it stays pending: only the job fails,
    and an operator retry queries again once the configuration is fixed.
    """

    message: str

    def apply(self, document: Document, job: Job) -> tuple[Document, Job]:
        updated = replace(_still_pending(document), updated_at=_now())
        return updated, _fail(job, category="fiscal_validation", message=self.message)


@dataclass(frozen=True, slots=True)
class RecordedAttempt:
    """Document and job to persist, and what else the record step does.

    ``retryable`` asks for the next attempt to be staged in the outbox;
    ``document_changed`` is false when only the job is closed, so no status
    webhook is published again.
    """

    document: Document
    job: Job
    retryable: bool
    document_changed: bool = True


def conclude_attempt(
    document: Document,
    job: Job,
    *,
    attempt_number: int,
    result: AttemptResult,
) -> RecordedAttempt:
    """Apply ``result`` and the attempt budget to rows this attempt holds."""

    updated_document, updated_job = result.apply(document, job)
    return _apply_attempt_budget(updated_document, updated_job, attempt_number)


def conclude_claimed_attempt(
    *,
    current_document: Document,
    current_job: Job,
    attempt_number: int,
    result: AttemptResult,
) -> RecordedAttempt | None:
    """Record ``result`` on rows re-read after the SIFEN call.

    Other writers may have run while SIFEN answered (an operator reconcile, a
    duplicate dispatch of the same job). Their work is respected:

    - a document that reached a terminal state is never moved away from it;
    - a terminal outcome of this attempt is always recorded, because it is
      SIFEN's final word on the document;
    - any other outcome is recorded only while this attempt still owns the
      job (no newer attempt claimed it); otherwise ``None`` is returned and
      nothing is written.
    """

    if current_document.internal_status in DOCUMENT_TERMINAL_STATUSES:
        if current_job.status in {"succeeded", "failed"}:
            return None
        return RecordedAttempt(
            document=current_document,
            job=_job_aligned_with(current_job, current_document),
            retryable=False,
            document_changed=False,
        )

    updated_document, updated_job = result.apply(current_document, current_job)
    if (
        updated_document.internal_status not in DOCUMENT_TERMINAL_STATUSES
        and current_job.attempts != attempt_number
    ):
        return None
    return _apply_attempt_budget(updated_document, updated_job, attempt_number)


def _apply_attempt_budget(
    document: Document,
    job: Job,
    attempt_number: int,
) -> RecordedAttempt:
    now = _now()
    if job.status != "retry_scheduled":
        if job.status in {"succeeded", "failed"}:
            job = replace(job, finished_at=now, updated_at=now)
        return RecordedAttempt(document=document, job=job, retryable=False)

    if attempt_number < MAX_DOCUMENT_ATTEMPTS:
        scheduled = replace(
            job,
            scheduled_at=_retry_at(attempt_number),
            updated_at=now,
        )
        return RecordedAttempt(document=document, job=scheduled, retryable=True)

    if document.internal_status == "queued":
        # Nothing ever reached SIFEN: the document stays queued with its
        # request, so an operator retry can send it as is.
        exhausted = _fail(
            job,
            category="retry_exhausted",
            message=_NEVER_DELIVERED_MESSAGE,
        )
        exhausted = replace(exhausted, finished_at=now, updated_at=now)
        return RecordedAttempt(document=document, job=exhausted, retryable=False)

    required_document, required_job = _mark_reconciliation_required(document, job)
    return RecordedAttempt(
        document=required_document,
        job=required_job,
        retryable=False,
    )


def _mark_reconciliation_required(
    document: Document,
    job: Job,
) -> tuple[Document, Job]:
    now = _now()
    return (
        replace(
            document,
            internal_status="reconciliation_required",
            sifen_status="reconciliation_required",
            sifen_result_message=_RECONCILIATION_REQUIRED_MESSAGE,
            updated_at=now,
        ),
        replace(
            job,
            status="failed",
            error_snapshot={
                "category": "reconciliation_required",
                "code": document.sifen_result_code,
                "message": _RECONCILIATION_REQUIRED_MESSAGE,
            },
            finished_at=now,
            updated_at=now,
        ),
    )


def _job_following(job: Job, document: Document, *, pending_category: str) -> Job:
    """Job state that follows a SIFEN answer recorded on ``document``."""

    status = job_status_for_document(document.internal_status)
    if status == "succeeded":
        return _succeed(job)
    if status == "failed":
        return replace(
            job,
            status="failed",
            error_snapshot={
                "category": "sifen_rejection",
                "code": document.sifen_result_code,
                "message": document.sifen_result_message,
            },
            updated_at=_now(),
        )
    return replace(
        job,
        status="retry_scheduled",
        error_snapshot={
            "category": pending_category,
            "code": document.sifen_result_code,
            "message": document.sifen_result_message,
        },
        updated_at=_now(),
    )


def _job_aligned_with(job: Job, document: Document) -> Job:
    """Close a job whose document another writer already finished."""

    now = _now()
    if job_status_for_document(document.internal_status) == "succeeded":
        return replace(
            _succeed(job),
            finished_at=now,
            updated_at=now,
        )
    return replace(
        job,
        status="failed",
        error_snapshot={
            "category": "concurrent_update",
            "code": document.sifen_result_code,
            "message": f"document became {document.internal_status} meanwhile",
        },
        finished_at=now,
        updated_at=now,
    )


def _succeed(job: Job) -> Job:
    return replace(job, status="succeeded", error_snapshot=None, updated_at=_now())


def _retry(job: Job, *, category: str, message: str) -> Job:
    return replace(
        job,
        status="retry_scheduled",
        error_snapshot={"category": category, "message": message},
        updated_at=_now(),
    )


def _fail(job: Job, *, category: str, message: str) -> Job:
    return replace(
        job,
        status="failed",
        error_snapshot={"category": category, "message": message},
        updated_at=_now(),
    )


def _still_pending(document: Document) -> Document:
    """An interrupted send is no longer in flight, but still unresolved."""

    if document.internal_status != DOCUMENT_SUBMITTING_STATUS:
        return document
    return replace(
        document,
        internal_status="retry_pending",
        sifen_status="retry_pending",
    )


def _has_prepared_request(document: Document) -> bool:
    return bool(document.sifen_request_xml and document.signed_xml and document.cdc)


def _retry_at(attempt_number: int) -> datetime:
    index = min(max(attempt_number - 1, 0), len(DOCUMENT_RETRY_DELAYS) - 1)
    return _now() + timedelta(seconds=DOCUMENT_RETRY_DELAYS[index])


def _now() -> datetime:
    return datetime.now(timezone.utc)
