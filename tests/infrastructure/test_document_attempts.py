"""Pure state rules of a document-emission attempt."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from kilasifen.domain.documents.models import Document
from kilasifen.domain.jobs.models import Job
from kilasifen.infrastructure.jobs.document_attempts import (
    MAX_DOCUMENT_ATTEMPTS,
    AttemptAction,
    OutcomeUnknown,
    ReconciliationRefused,
    RequestNotSent,
    SifenAnswered,
    conclude_attempt,
    conclude_claimed_attempt,
    select_action,
)
from kilasifen.infrastructure.sifen.engine import SubmissionOutcome

_APPROVED = SubmissionOutcome(
    response_raw="<rRetEnviDe/>",
    sifen_status="approved",
    result_code="0260",
    result_message="Aprobado",
)


@pytest.mark.parametrize(
    ("status", "has_request", "expected"),
    [
        ("queued", False, AttemptAction.PREPARE),
        ("queued", True, AttemptAction.RESEND),
        ("failed", True, AttemptAction.PREPARE),
        ("submitting", True, AttemptAction.RECONCILE),
        ("submitted", True, AttemptAction.RECONCILE),
        ("retry_pending", True, AttemptAction.RECONCILE),
        ("reconciliation_required", True, AttemptAction.RECONCILE),
    ],
)
def test_select_action(status: str, has_request: bool, expected: AttemptAction) -> None:
    document = _document(status=status, with_request=has_request)

    assert select_action(document) is expected


def test_a_document_that_may_be_at_sifen_is_never_resent_without_cdc() -> None:
    document = replace(_document(status="retry_pending"), cdc=None)

    assert select_action(document) is AttemptAction.PREPARE


def test_terminal_documents_are_never_moved_by_a_late_outcome() -> None:
    recorded = conclude_claimed_attempt(
        current_document=_document(status="approved"),
        current_job=_job(status="processing", attempts=1),
        attempt_number=1,
        result=OutcomeUnknown("timeout"),
    )

    assert recorded is not None
    assert recorded.document.internal_status == "approved"
    assert recorded.job.status == "succeeded"
    assert recorded.retryable is False
    assert recorded.document_changed is False


def test_nothing_is_written_when_document_and_job_are_already_final() -> None:
    assert (
        conclude_claimed_attempt(
            current_document=_document(status="cancelled"),
            current_job=_job(status="succeeded", attempts=1),
            attempt_number=1,
            result=SifenAnswered(_APPROVED),
        )
        is None
    )


def test_only_the_newest_attempt_records_an_intermediate_outcome() -> None:
    current_job = _job(status="processing", attempts=3)
    submitting = _document(status="submitting")

    stale = conclude_claimed_attempt(
        current_document=submitting,
        current_job=current_job,
        attempt_number=2,
        result=RequestNotSent("no salio"),
    )
    final = conclude_claimed_attempt(
        current_document=submitting,
        current_job=current_job,
        attempt_number=2,
        result=SifenAnswered(_APPROVED),
    )

    assert stale is None
    assert final is not None and final.document.internal_status == "approved"


def test_a_refused_query_fails_the_job_but_keeps_the_document_pending() -> None:
    recorded = conclude_attempt(
        _document(status="submitting"),
        _job(status="processing", attempts=1),
        attempt_number=1,
        result=ReconciliationRefused("Emitter tax environment does not match"),
    )

    assert recorded.document.internal_status == "retry_pending"
    assert recorded.job.status == "failed"
    assert recorded.job.error_snapshot["category"] == "fiscal_validation"


def test_budget_exhaustion_depends_on_whether_sifen_may_hold_the_document() -> None:
    never_sent = conclude_attempt(
        _document(status="submitting"),
        _job(status="processing", attempts=MAX_DOCUMENT_ATTEMPTS),
        attempt_number=MAX_DOCUMENT_ATTEMPTS,
        result=RequestNotSent("no salio"),
    )
    unknown = conclude_attempt(
        _document(status="submitting"),
        _job(status="processing", attempts=MAX_DOCUMENT_ATTEMPTS),
        attempt_number=MAX_DOCUMENT_ATTEMPTS,
        result=OutcomeUnknown("timeout"),
    )

    assert never_sent.document.internal_status == "queued"
    assert never_sent.job.error_snapshot["category"] == "retry_exhausted"
    assert unknown.document.internal_status == "reconciliation_required"
    assert unknown.job.error_snapshot["category"] == "reconciliation_required"
    assert never_sent.retryable is unknown.retryable is False


def _document(*, status: str, with_request: bool = True) -> Document:
    now = datetime.now(timezone.utc)
    return Document(
        id="document-1",
        emitter_id="emitter-1",
        external_id=None,
        idempotency_key=None,
        document_type="factura",
        payload_snapshot={},
        generated_xml="<rDE/>" if with_request else None,
        signed_xml="<rDE><Signature/></rDE>" if with_request else None,
        sifen_request_xml="<rEnviDe/>" if with_request else None,
        sifen_response_raw=None,
        last_query_request_xml=None,
        last_query_response_raw=None,
        last_query_at=None,
        cdc="0180012345" if with_request else None,
        internal_status=status,
        sifen_status=None,
        sifen_result_code=None,
        sifen_result_message=None,
        created_at=now,
        updated_at=now,
    )


def _job(*, status: str, attempts: int) -> Job:
    now = datetime.now(timezone.utc)
    return Job(
        id="job-1",
        emitter_id="emitter-1",
        related_entity_type="document",
        related_entity_id="document-1",
        job_type="document.emit",
        status=status,
        attempts=attempts,
        error_snapshot=None,
        scheduled_at=now,
        started_at=now,
        finished_at=None,
        worker_correlation_id=None,
        created_at=now,
        updated_at=now,
    )
