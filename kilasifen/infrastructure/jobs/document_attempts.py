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
and I/O. What the next attempt does follows SIFEN's last word on the CDC
(DECISIONES F60, F61, F63, F64):

- a document that may already be at SIFEN is first queried by CDC; 0422
  makes it approved (cancelled if a cancellation is registered) and it is
  never sent again; 0420 lets the same signed DE travel again;
- a rejection with 1001/1002 is only believed after that query;
- a rejection with 0161/0162 (server failures) is sent again;
- a request that provably never left is sent again.

Every resend carries the same signed ``rDE`` (same CDC, signature and
``dFecFirma``) in a new ``rEnviDe`` with a fresh ``dId``, stored by the first
transaction before it travels.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Protocol

from kilasifen.domain.common.fiscal_states import (
    DOCUMENT_APPROVED_STATUSES,
    DOCUMENT_PENDING_STATUSES,
    DOCUMENT_POSSIBLY_RECEIVED_STATUSES,
    DOCUMENT_SUBMITTING_STATUS,
    DOCUMENT_TERMINAL_STATUSES,
    job_status_for_document,
)
from kilasifen.domain.common.sifen_results import (
    DUPLICATE_DOCUMENT_CODES,
    SERVER_FAILURE_CODES,
)
from kilasifen.domain.documents.models import Document
from kilasifen.domain.documents.transmission_deadlines import (
    DeadlineAlert,
    transmission_deadline_alerts,
)
from kilasifen.domain.jobs.models import Job
from kilasifen.infrastructure.sifen.de_facts import approval_lower_bound, read_de_facts
from kilasifen.infrastructure.sifen.engine import PreparedSubmission, SubmissionOutcome
from kilasifen.infrastructure.sifen.query import (
    QUERY_FOUND,
    QUERY_NOT_FOUND_OR_NOT_APPROVED,
    DocumentQueryOutcome,
)
from kilasifen.infrastructure.sifen.reconciliation import (
    document_found_at_sifen,
    document_not_approved_at_sifen,
)

MAX_DOCUMENT_ATTEMPTS = 5
DOCUMENT_RETRY_DELAYS = (30, 120, 600, 1800)

_RECONCILIATION_REQUIRED_MESSAGE = (
    "automatic attempts exhausted while SIFEN's answer for the CDC is unknown; "
    "an operator retry queries the CDC again"
)
_NOT_DELIVERED_MESSAGE = (
    "SIFEN holds no approved DTE for this CDC (never delivered, or answered "
    "0420); a manual retry sends the same signed document again"
)
_SERVER_FAILURE_EXHAUSTED_MESSAGE = (
    "SIFEN kept answering a server failure (0161/0162); a manual retry sends "
    "the same signed document again"
)


class AttemptAction(str, Enum):
    """What one attempt does with its document."""

    PREPARE = "prepare"
    """Build and sign the document, persist the request, send it."""

    RESEND = "resend"
    """Send the stored signed DE again, in a new ``rEnviDe``."""

    RECONCILE = "reconcile"
    """Query the CDC; the document may already be at SIFEN."""


def select_action(document: Document) -> AttemptAction:
    """Decide what the next attempt does with ``document``."""

    if document.internal_status in DOCUMENT_POSSIBLY_RECEIVED_STATUSES and document.cdc:
        return AttemptAction.RECONCILE
    if _awaits_resend(document):
        return AttemptAction.RESEND
    return AttemptAction.PREPARE


def is_finished(document: Document, job: Job) -> bool:
    """Tell whether the job has nothing left to do.

    Two terminal documents still run: a ``failed`` one whose job an operator
    queued again, and one rejected with a server failure (0161/0162) while its
    job is scheduled or queued again (DECISIONES F64).
    """

    if document.internal_status not in DOCUMENT_TERMINAL_STATUSES:
        return False
    if document.internal_status == "failed":
        return job.status != "queued"
    if _rejected_by_server_failure(document):
        return job.status not in {"queued", "retry_scheduled"}
    return True


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
    *,
    request_xml: str | None = None,
    timbrado: str | None = None,
) -> Document:
    """Persist what is about to be sent.

    ``prepared`` comes from a fresh preparation; on a resend ``request_xml``
    is the new ``rEnviDe`` around the stored signed DE.
    """

    if prepared is not None:
        document = replace(
            document,
            generated_xml=prepared.generated_xml,
            signed_xml=prepared.signed_xml,
            sifen_request_xml=prepared.request_xml,
            cdc=prepared.cdc,
            timbrado=timbrado or document.timbrado,
        )
    elif request_xml is not None:
        document = replace(document, sifen_request_xml=request_xml)
    return replace(
        document,
        internal_status=DOCUMENT_SUBMITTING_STATUS,
        retryable_server_error=False,
        updated_at=_now(),
    )


class AttemptResult(Protocol):
    """Outcome of one attempt, applied to the document and job it belongs to."""

    def apply(self, document: Document, job: Job) -> tuple[Document, Job]:
        """Return the document and job that record this outcome."""


@dataclass(frozen=True, slots=True)
class SifenAnswered:
    """SIFEN answered the submission.

    The transport already classified the answer by ``dEstRes`` (DECISIONES
    F60). An approval keeps ``dProtAut`` and ``dFecProc``, the start of the
    cancellation window (MT v150 §6.2.1 p. 25); without ``dFecProc`` a lower
    bound of the approval is kept instead. An answer the platform cannot
    classify is never read as a rejection: the CDC is queried next.
    """

    outcome: SubmissionOutcome

    def apply(self, document: Document, job: Job) -> tuple[Document, Job]:
        outcome = self.outcome
        answered = replace(
            document,
            sifen_response_raw=outcome.response_raw,
            sifen_result_code=outcome.result_code,
            sifen_result_message=outcome.result_message,
            sifen_messages=[message.as_dict() for message in outcome.messages]
            or None,
            retryable_server_error=False,
            updated_at=_now(),
        )
        if outcome.sifen_status in DOCUMENT_APPROVED_STATUSES:
            approved = replace(
                answered,
                internal_status=outcome.sifen_status,
                sifen_status=outcome.sifen_status,
                sifen_protocol=outcome.protocol or document.sifen_protocol,
                sifen_approved_at=outcome.processed_at
                or approval_lower_bound(document),
            )
            return approved, _succeed(job)
        if outcome.sifen_status == "rejected":
            return _record_rejection(answered, job)
        pending = replace(
            answered, internal_status="retry_pending", sifen_status="retry_pending"
        )
        return pending, _job_following(
            job, pending, pending_category="sifen_unclassified"
        )


@dataclass(frozen=True, slots=True)
class SifenRejected:
    """The transport reported a functional rejection from SIFEN."""

    code: str
    message: str

    def apply(self, document: Document, job: Job) -> tuple[Document, Job]:
        answered = replace(
            document,
            sifen_result_code=self.code,
            sifen_result_message=self.message,
            sifen_messages=[{"code": self.code, "message": self.message}],
            retryable_server_error=False,
            updated_at=_now(),
        )
        return _record_rejection(answered, job)


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
    """SIFEN answered the query by CDC (DECISIONES F61, F62, F63)."""

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
        if self.outcome.status == QUERY_FOUND:
            return document_found_at_sifen(traced, self.outcome), _succeed(job)
        if self.outcome.status == QUERY_NOT_FOUND_OR_NOT_APPROVED:
            settled = document_not_approved_at_sifen(traced)
            if settled.internal_status == "rejected":
                return settled, _rejected_job(job, settled)
            # The same signed DE travels again on the next attempt.
            return settled, _job_following(
                job, settled, pending_category="resubmission"
            )
        # Any other code is an error of the query, not an answer on the CDC.
        pending = replace(
            traced,
            internal_status="retry_pending",
            sifen_status="retry_pending",
        )
        return pending, _job_following(
            job, pending, pending_category="reconciliation_pending"
        )


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
    webhook is published again. ``deadline_alerts`` are the transmission
    deadlines a still unapproved document is close to, or past.
    """

    document: Document
    job: Job
    retryable: bool
    document_changed: bool = True
    deadline_alerts: tuple[DeadlineAlert, ...] = ()


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
    settled = updated_document.internal_status in DOCUMENT_TERMINAL_STATUSES and not (
        _rejected_by_server_failure(updated_document)
    )
    if not settled and current_job.attempts != attempt_number:
        return None
    return _apply_attempt_budget(updated_document, updated_job, attempt_number)


def _record_rejection(document: Document, job: Job) -> tuple[Document, Job]:
    """Record a Rechazado according to its code (first error, Dto 872 Art. 29).

    - 1001/1002 only fire when another document is AUTHORIZED (MT v150 §12.4
      val. 2-3, p. 159): the CDC is queried before the rejection is believed
      (DECISIONES F61).
    - 0161/0162 are server failures reported with state R (MT v150 §12.2.6,
      p. 153). Reading them as a resendable rejection is NO DETERMINADO
      (DECISIONES F64): the document stays ``rejected`` with
      ``retryable_server_error`` and its signed XML is sent again within the
      attempt budget.
    """

    code = document.sifen_result_code
    if code in DUPLICATE_DOCUMENT_CODES:
        pending = replace(
            document, internal_status="retry_pending", sifen_status="retry_pending"
        )
        return pending, _job_following(
            job, pending, pending_category="duplicate_reconciliation"
        )
    rejected = replace(
        document,
        internal_status="rejected",
        sifen_status="rejected",
        retryable_server_error=code in SERVER_FAILURE_CODES,
    )
    if rejected.retryable_server_error:
        return rejected, replace(
            job,
            status="retry_scheduled",
            error_snapshot={
                "category": "retryable_server_error",
                "code": code,
                "message": rejected.sifen_result_message,
            },
            updated_at=_now(),
        )
    return rejected, _rejected_job(job, rejected)


def _apply_attempt_budget(
    document: Document,
    job: Job,
    attempt_number: int,
) -> RecordedAttempt:
    now = _now()
    if job.status != "retry_scheduled":
        if job.status in {"succeeded", "failed"}:
            job = replace(job, finished_at=now, updated_at=now)
        return _with_deadline_alerts(
            RecordedAttempt(document=document, job=job, retryable=False)
        )

    if attempt_number < MAX_DOCUMENT_ATTEMPTS:
        scheduled = replace(
            job,
            scheduled_at=_retry_at(attempt_number),
            updated_at=now,
        )
        return _with_deadline_alerts(
            RecordedAttempt(document=document, job=scheduled, retryable=True)
        )

    if document.internal_status == "queued" or _rejected_by_server_failure(document):
        # SIFEN holds no DTE for the CDC: the document keeps its signed XML
        # and an operator retry sends it again.
        message = (
            _NOT_DELIVERED_MESSAGE
            if document.internal_status == "queued"
            else _SERVER_FAILURE_EXHAUSTED_MESSAGE
        )
        exhausted = _fail(job, category="retry_exhausted", message=message)
        exhausted = replace(exhausted, finished_at=now, updated_at=now)
        return _with_deadline_alerts(
            RecordedAttempt(document=document, job=exhausted, retryable=False)
        )

    required_document, required_job = _mark_reconciliation_required(document, job)
    return _with_deadline_alerts(
        RecordedAttempt(
            document=required_document,
            job=required_job,
            retryable=False,
        )
    )


def _with_deadline_alerts(recorded: RecordedAttempt) -> RecordedAttempt:
    """Add the 72 h / 720 h alerts of a document SIFEN has not approved yet.

    The alerts go into the job ``error_snapshot`` (visible through the jobs
    API) and are logged by the worker (DECISIONES F63).
    """

    document = recorded.document
    if not (
        document.internal_status in DOCUMENT_PENDING_STATUSES
        or _rejected_by_server_failure(document)
    ):
        return recorded
    facts = read_de_facts(document.signed_xml)
    alerts = transmission_deadline_alerts(
        signed_at=facts.signed_at,
        issued_at=facts.issued_at,
        now=_now(),
    )
    if not alerts:
        return recorded
    snapshot = dict(recorded.job.error_snapshot or {})
    snapshot["deadline_alerts"] = [alert.value for alert in alerts]
    return replace(
        recorded,
        job=replace(recorded.job, error_snapshot=snapshot),
        deadline_alerts=alerts,
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
        return _rejected_job(job, document)
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


def _rejected_job(job: Job, document: Document) -> Job:
    """Job state after SIFEN's final rejection of ``document``."""

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


def _awaits_resend(document: Document) -> bool:
    """SIFEN holds no DTE for the CDC and the signed DE can travel again."""

    if not (document.signed_xml and document.cdc):
        return False
    return document.internal_status == "queued" or _rejected_by_server_failure(
        document
    )


def _rejected_by_server_failure(document: Document) -> bool:
    return document.internal_status == "rejected" and document.retryable_server_error


def _retry_at(attempt_number: int) -> datetime:
    index = min(max(attempt_number - 1, 0), len(DOCUMENT_RETRY_DELAYS) - 1)
    return _now() + timedelta(seconds=DOCUMENT_RETRY_DELAYS[index])


def _now() -> datetime:
    return datetime.now(timezone.utc)
