import pytest

from kilasifen.domain.common.fiscal_states import (
    job_status_for_document,
    normalize_document_status,
    require_document_transition,
)


@pytest.mark.parametrize("status", ["approved", "approved_with_observation"])
def test_approved_document_states_complete_the_job(status: str) -> None:
    assert job_status_for_document(status) == "succeeded"


@pytest.mark.parametrize(
    "status",
    [
        "queued",
        "processing",
        "submitted",
        "retry_pending",
        "reconciliation_required",
    ],
)
def test_pending_document_states_require_reconciliation(status: str) -> None:
    assert job_status_for_document(status) == "retry_scheduled"


@pytest.mark.parametrize("status", ["rejected", "failed", "cancelled"])
def test_terminal_unsuccessful_document_states_fail_the_job(status: str) -> None:
    assert job_status_for_document(status) == "failed"


def test_empty_upstream_status_is_pending_not_approved() -> None:
    assert normalize_document_status(None) == "submitted"
    assert job_status_for_document("") == "retry_scheduled"


def test_terminal_document_cannot_transition_to_another_state() -> None:
    with pytest.raises(ValueError, match="invalid terminal document transition"):
        require_document_transition("approved", "submitted")


def test_terminal_document_can_be_observed_idempotently() -> None:
    assert require_document_transition("approved", "approved") == "approved"


def test_inutilized_is_a_terminal_unsuccessful_state() -> None:
    assert job_status_for_document("inutilized") == "failed"
    with pytest.raises(ValueError, match="invalid terminal document transition"):
        require_document_transition("inutilized", "queued")


@pytest.mark.parametrize(
    ("current", "target"),
    [
        # Dto 872/2023 Art. 30: an approved DTE can be cancelled.
        ("approved", "cancelled"),
        ("approved_with_observation", "cancelled"),
        # Dto 872/2023 Art. 29 and MT v150 §6.5: a rejected DE is sent again
        # with the same CDC or its number is inutilized.
        ("rejected", "submitting"),
        ("rejected", "inutilized"),
        # Dto 872/2023 Art. 31: a DE that never reached SIFEN.
        ("failed", "queued"),
        ("failed", "inutilized"),
    ],
)
def test_terminal_exits_allowed_by_the_regulation(current: str, target: str) -> None:
    assert require_document_transition(current, target) == target


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("approved", "inutilized"),
        ("cancelled", "approved"),
        ("cancelled", "inutilized"),
        ("rejected", "approved"),
    ],
)
def test_terminal_exits_the_regulation_forbids(current: str, target: str) -> None:
    with pytest.raises(ValueError, match="invalid terminal document transition"):
        require_document_transition(current, target)
