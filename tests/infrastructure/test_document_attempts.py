"""Pure state rules of a document-emission attempt."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from kilasifen.domain.documents.models import Document
from kilasifen.domain.jobs.models import Job
from kilasifen.infrastructure.jobs.document_attempts import (
    MAX_DOCUMENT_ATTEMPTS,
    AttemptAction,
    OutcomeUnknown,
    Reconciled,
    ReconciliationRefused,
    RequestNotSent,
    SifenAnswered,
    conclude_attempt,
    conclude_claimed_attempt,
    is_finished,
    mark_submitting,
    select_action,
)
from kilasifen.infrastructure.sifen.engine import SubmissionOutcome
from kilasifen.infrastructure.sifen.query import (
    QUERY_ERROR,
    QUERY_FOUND,
    QUERY_NOT_FOUND_OR_NOT_APPROVED,
    DocumentQueryOutcome,
)
from kilasifen.infrastructure.sifen.responses import (
    DocumentContainer,
    RegisteredEvent,
    SifenMessage,
)

_APPROVED = SubmissionOutcome(
    response_raw="<rRetEnviDe/>",
    sifen_status="approved",
    result_code="0260",
    result_message="Aprobado",
)
_CDC = "0180012345"
_PARAGUAY = timezone(timedelta(hours=-3))
_SIGNED_AT = (
    '<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd"><DE Id="0180012345">'
    "<dFecFirma>{signed}</dFecFirma>"
    "<gDatGralOpe><dFeEmiDE>{signed}</dFeEmiDE></gDatGralOpe>"
    "</DE><Signature/></rDE>"
)


@pytest.mark.parametrize(
    ("status", "has_request", "expected"),
    [
        ("queued", False, AttemptAction.PREPARE),
        ("queued", True, AttemptAction.RESEND),
        ("failed", True, AttemptAction.PREPARE),
        ("rejected", True, AttemptAction.PREPARE),
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
    server_failure = conclude_claimed_attempt(
        current_document=submitting,
        current_job=current_job,
        attempt_number=2,
        result=SifenAnswered(_answer("rejected", "0161")),
    )

    assert stale is None
    assert final is not None and final.document.internal_status == "approved"
    # A 0161/0162 rejection is sent again, so it is not SIFEN's final word.
    assert server_failure is None


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


# --- DECISIONES F60/F61/F63/F64: what SIFEN's answers mean ----------------


def test_an_observed_approval_is_a_dte_with_its_protocol_and_dFecProc() -> None:
    processed_at = datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc)
    recorded = conclude_attempt(
        _document(status="submitting"),
        _job(status="processing", attempts=1),
        attempt_number=1,
        result=SifenAnswered(
            _answer(
                "approved_with_observation",
                "1005",
                protocol="1234567890",
                processed_at=processed_at,
            )
        ),
    )

    assert recorded.document.internal_status == "approved_with_observation"
    assert recorded.document.sifen_protocol == "1234567890"
    assert recorded.document.sifen_approved_at == processed_at
    assert recorded.document.sifen_messages == [
        {"code": "1005", "message": "mensaje 1005"}
    ]
    assert recorded.job.status == "succeeded"


def test_an_approval_without_dFecProc_keeps_a_lower_bound_of_it() -> None:
    document = _document(status="submitting")
    recorded = conclude_attempt(
        document,
        _job(status="processing", attempts=1),
        attempt_number=1,
        result=SifenAnswered(_answer("approved", "0260")),
    )

    # No dFecFirma in this signed XML: the creation time is the bound.
    assert recorded.document.sifen_approved_at == document.created_at


def test_an_unclassified_answer_is_queried_next_not_rejected() -> None:
    recorded = conclude_attempt(
        _document(status="submitting"),
        _job(status="processing", attempts=1),
        attempt_number=1,
        result=SifenAnswered(_answer("unknown", "1330")),
    )

    assert recorded.document.internal_status == "retry_pending"
    assert recorded.job.error_snapshot["category"] == "sifen_unclassified"
    assert select_action(recorded.document) is AttemptAction.RECONCILE


@pytest.mark.parametrize("code", ["1001", "1002"])
def test_a_duplicate_rejection_is_only_believed_after_querying_the_cdc(
    code: str,
) -> None:
    # MT v150 §12.4 val. 2-3 (p. 159); DECISIONES F61.
    answered = conclude_attempt(
        _document(status="submitting"),
        _job(status="processing", attempts=1),
        attempt_number=1,
        result=SifenAnswered(_answer("rejected", code)),
    )

    assert answered.document.internal_status == "retry_pending"
    assert answered.job.error_snapshot["category"] == "duplicate_reconciliation"
    assert select_action(answered.document) is AttemptAction.RECONCILE

    approved = conclude_attempt(
        answered.document,
        _job(status="processing", attempts=2),
        attempt_number=2,
        result=Reconciled(_query(QUERY_FOUND)),
    )
    rejected = conclude_attempt(
        answered.document,
        _job(status="processing", attempts=2),
        attempt_number=2,
        result=Reconciled(_query(QUERY_NOT_FOUND_OR_NOT_APPROVED)),
    )

    assert approved.document.internal_status == "approved"
    assert approved.job.status == "succeeded"
    assert rejected.document.internal_status == "rejected"
    assert rejected.document.sifen_result_code == code
    assert rejected.job.status == "failed"


def test_a_query_error_never_settles_a_duplicate_rejection() -> None:
    answered = conclude_attempt(
        _document(status="submitting"),
        _job(status="processing", attempts=1),
        attempt_number=1,
        result=SifenAnswered(_answer("rejected", "1002")),
    )
    unanswered = conclude_attempt(
        answered.document,
        _job(status="processing", attempts=2),
        attempt_number=2,
        result=Reconciled(_query(QUERY_ERROR)),
    )
    settled = conclude_attempt(
        unanswered.document,
        _job(status="processing", attempts=3),
        attempt_number=3,
        result=Reconciled(_query(QUERY_NOT_FOUND_OR_NOT_APPROVED)),
    )

    assert unanswered.document.internal_status == "retry_pending"
    assert settled.document.internal_status == "rejected"
    assert settled.document.sifen_result_code == "1002"


@pytest.mark.parametrize("code", ["0161", "0162"])
def test_a_server_failure_is_a_rejection_that_is_sent_again(code: str) -> None:
    # MT v150 §12.2.6 (p. 153); DECISIONES F64 (NO DETERMINADO).
    recorded = conclude_attempt(
        _document(status="submitting"),
        _job(status="processing", attempts=1),
        attempt_number=1,
        result=SifenAnswered(_answer("rejected", code)),
    )

    document, job = recorded.document, recorded.job
    assert document.internal_status == "rejected"
    assert document.retryable_server_error is True
    assert job.status == "retry_scheduled" and recorded.retryable is True
    assert job.error_snapshot["category"] == "retryable_server_error"
    assert select_action(document) is AttemptAction.RESEND
    assert is_finished(document, job) is False

    exhausted = conclude_attempt(
        _document(status="submitting"),
        _job(status="processing", attempts=MAX_DOCUMENT_ATTEMPTS),
        attempt_number=MAX_DOCUMENT_ATTEMPTS,
        result=SifenAnswered(_answer("rejected", code)),
    )
    assert exhausted.document.internal_status == "rejected"
    assert exhausted.document.retryable_server_error is True
    assert exhausted.job.status == "failed"
    assert exhausted.job.error_snapshot["category"] == "retry_exhausted"
    assert is_finished(exhausted.document, exhausted.job) is True
    # An operator retry queues the job and the same signed DE travels again.
    requeued = replace(exhausted.job, status="queued")
    assert is_finished(exhausted.document, requeued) is False


def _listed_after(first: str, second: str) -> SubmissionOutcome:
    """A Rechazado whose ``gResProc`` lists ``second`` after ``first``."""

    return SubmissionOutcome(
        response_raw="<rRetEnviDe/>",
        sifen_status="rejected",
        result_code=first,
        result_message=f"mensaje {first}",
        messages=(
            SifenMessage(code=first, message=f"mensaje {first}"),
            SifenMessage(code=second, message=f"mensaje {second}"),
        ),
    )


@pytest.mark.parametrize("code", ["1001", "1002"])
def test_a_duplicate_code_in_any_message_is_queried_first(code: str) -> None:
    """The order of ``gResProc`` is NO DETERMINADO (DOSSIER R1 R11)."""

    answered = conclude_attempt(
        _document(status="submitting"),
        _job(status="processing", attempts=1),
        attempt_number=1,
        result=SifenAnswered(_listed_after("1330", code)),
    )

    assert answered.document.internal_status == "retry_pending"
    assert answered.job.error_snapshot["category"] == "duplicate_reconciliation"

    approved = conclude_attempt(
        answered.document,
        _job(status="processing", attempts=2),
        attempt_number=2,
        result=Reconciled(_query(QUERY_FOUND)),
    )
    rejected = conclude_attempt(
        answered.document,
        _job(status="processing", attempts=2),
        attempt_number=2,
        result=Reconciled(_query(QUERY_NOT_FOUND_OR_NOT_APPROVED)),
    )

    assert approved.document.internal_status == "approved"
    assert rejected.document.internal_status == "rejected"
    # The rejection keeps the first error SIFEN reported (Dto 872 Art. 29).
    assert rejected.document.sifen_result_code == "1330"


@pytest.mark.parametrize("code", ["0161", "0162"])
def test_a_server_failure_in_any_message_is_sent_again(code: str) -> None:
    recorded = conclude_attempt(
        _document(status="submitting"),
        _job(status="processing", attempts=1),
        attempt_number=1,
        result=SifenAnswered(_listed_after("1330", code)),
    )

    assert recorded.document.internal_status == "rejected"
    assert recorded.document.retryable_server_error is True
    assert recorded.document.sifen_result_code == "1330"
    assert recorded.job.error_snapshot["category"] == "retryable_server_error"
    assert select_action(recorded.document) is AttemptAction.RESEND


def _malformed(message: str, *other_codes: str) -> SubmissionOutcome:
    """A Rechazado 0160 with ``message``, followed by ``other_codes``."""

    messages = (SifenMessage(code="0160", message=message),) + tuple(
        SifenMessage(code=code, message=f"mensaje {code}") for code in other_codes
    )
    return SubmissionOutcome(
        response_raw="<rRetEnviDe/>",
        sifen_status="rejected",
        result_code="0160",
        result_message=message,
        messages=messages,
    )


def test_a_bare_0160_is_a_rejection_that_is_sent_again() -> None:
    # MT v150 §12.2.6 (AE01, p. 153) and §6.5 (p. 26); DECISIONES F67: the
    # test environment answered it to valid requests that passed later.
    recorded = conclude_attempt(
        _document(status="submitting"),
        _job(status="processing", attempts=1),
        attempt_number=1,
        result=SifenAnswered(_malformed("XML Mal Formado.")),
    )

    document, job = recorded.document, recorded.job
    assert document.internal_status == "rejected"
    assert document.retryable_server_error is True
    assert job.status == "retry_scheduled" and recorded.retryable is True
    assert job.error_snapshot["code"] == "0160"
    assert select_action(document) is AttemptAction.RESEND

    exhausted = conclude_attempt(
        _document(status="submitting"),
        _job(status="processing", attempts=MAX_DOCUMENT_ATTEMPTS),
        attempt_number=MAX_DOCUMENT_ATTEMPTS,
        result=SifenAnswered(_malformed("XML Mal Formado.")),
    )
    assert exhausted.document.internal_status == "rejected"
    assert exhausted.job.status == "failed"
    assert exhausted.job.error_snapshot["category"] == "retry_exhausted"


@pytest.mark.parametrize(
    "message",
    [
        # Guia de Mejores Practicas DNIT oct-2024 (p. 11).
        "XML malformado: [El valor del elemento: dDirRec es invalido, "
        "El valor del elemento: dDirLocEnt es invalido]",
        "XML malformado: cvc-datatype-valid.1.2.3: 'Otro' is not a valid value "
        "of union type",
    ],
)
def test_a_0160_with_a_validation_detail_is_final(message: str) -> None:
    # A content error: the same DE would be rejected again (DECISIONES F67).
    recorded = conclude_attempt(
        _document(status="submitting"),
        _job(status="processing", attempts=1),
        attempt_number=1,
        result=SifenAnswered(_malformed(message)),
    )

    assert recorded.document.internal_status == "rejected"
    assert recorded.document.retryable_server_error is False
    assert recorded.job.status == "failed"


def test_a_0160_next_to_another_code_is_final() -> None:
    recorded = conclude_attempt(
        _document(status="submitting"),
        _job(status="processing", attempts=1),
        attempt_number=1,
        result=SifenAnswered(_malformed("XML Mal Formado.", "1330")),
    )

    assert recorded.document.retryable_server_error is False
    assert recorded.job.status == "failed"


def test_a_fiscal_rejection_is_final() -> None:
    recorded = conclude_attempt(
        _document(status="submitting"),
        _job(status="processing", attempts=1),
        attempt_number=1,
        result=SifenAnswered(_answer("rejected", "1330")),
    )

    assert recorded.document.internal_status == "rejected"
    assert recorded.document.retryable_server_error is False
    assert recorded.job.status == "failed"
    assert is_finished(recorded.document, replace(recorded.job, status="queued"))


def test_a_cancellation_found_by_query_cancels_and_keeps_the_signed_xml() -> None:
    document = _document(status="retry_pending")
    recorded = conclude_attempt(
        document,
        _job(status="processing", attempts=2),
        attempt_number=2,
        result=Reconciled(
            _query(
                QUERY_FOUND,
                container=DocumentContainer(
                    document_xml="<rDE>copia de la SET</rDE>",
                    protocol="5566778899",
                    events=(
                        RegisteredEvent(
                            kind="cancelacion",
                            cdc=_CDC,
                            protocol="1",
                            state_text="Aprobado",
                        ),
                    ),
                ),
            )
        ),
    )

    assert recorded.document.internal_status == "cancelled"
    assert recorded.document.signed_xml == document.signed_xml
    assert recorded.document.sifen_protocol == "5566778899"
    assert recorded.job.status == "succeeded"


def test_a_cdc_not_approved_is_queued_to_travel_again() -> None:
    recorded = conclude_attempt(
        _document(status="retry_pending"),
        _job(status="processing", attempts=2),
        attempt_number=2,
        result=Reconciled(_query(QUERY_NOT_FOUND_OR_NOT_APPROVED)),
    )

    assert recorded.document.internal_status == "queued"
    assert recorded.job.error_snapshot["category"] == "resubmission"
    assert select_action(recorded.document) is AttemptAction.RESEND


def test_mark_submitting_on_a_resend_stores_the_new_request() -> None:
    document = replace(_document(status="rejected"), retryable_server_error=True)

    submitting = mark_submitting(document, request_xml="<rEnviDe><dId>2</dId>")

    assert submitting.internal_status == "submitting"
    assert submitting.sifen_request_xml == "<rEnviDe><dId>2</dId>"
    assert submitting.signed_xml == document.signed_xml
    assert submitting.retryable_server_error is False


@pytest.mark.parametrize(
    ("hours_ago", "expected"),
    [
        (10, None),
        (50, ["late_transmission_soon"]),
        (80, ["late_transmission"]),
        (710, ["late_transmission", "emission_rejection_soon"]),
        (730, ["late_transmission", "emission_rejection"]),
    ],
)
def test_a_pending_document_raises_the_72h_and_720h_alerts(
    hours_ago: int,
    expected: list[str] | None,
) -> None:
    # Dto 872/2023 Art. 27 (72 h, AO 1005); MT v150 §12.4 val. 19 (720 h,
    # 1150); DECISIONES F63.
    document = replace(
        _document(status="submitting"),
        signed_xml=_signed_hours_ago(hours_ago),
    )

    recorded = conclude_attempt(
        document,
        _job(status="processing", attempts=1),
        attempt_number=1,
        result=OutcomeUnknown("timeout"),
    )

    assert recorded.job.error_snapshot.get("deadline_alerts") == expected
    assert [alert.value for alert in recorded.deadline_alerts] == (expected or [])


def test_an_approved_document_raises_no_deadline_alert() -> None:
    document = replace(
        _document(status="submitting"),
        signed_xml=_signed_hours_ago(100),
    )

    recorded = conclude_attempt(
        document,
        _job(status="processing", attempts=1),
        attempt_number=1,
        result=SifenAnswered(_answer("approved_with_observation", "1005")),
    )

    assert recorded.deadline_alerts == ()
    assert recorded.job.error_snapshot is None


def _signed_hours_ago(hours: int) -> str:
    signed = (datetime.now(_PARAGUAY) - timedelta(hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    return _SIGNED_AT.format(signed=signed)


def _answer(status: str, code: str, **extra) -> SubmissionOutcome:
    return SubmissionOutcome(
        response_raw="<rRetEnviDe/>",
        sifen_status=status,
        result_code=code,
        result_message=f"mensaje {code}",
        messages=(SifenMessage(code=code, message=f"mensaje {code}"),),
        **extra,
    )


def _query(status: str, *, container=None) -> DocumentQueryOutcome:
    codes = {QUERY_FOUND: "0422", QUERY_NOT_FOUND_OR_NOT_APPROVED: "0420"}
    return DocumentQueryOutcome(
        cdc=_CDC,
        request_xml="<rEnviConsDeRequest/>",
        response_raw="<rEnviConsDeResponse/>",
        result_code=codes.get(status, "0421"),
        result_message="consulta",
        status=status,
        content_xml=None,
        processed_at=None,
        container=container,
    )


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
        cdc=_CDC if with_request else None,
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
