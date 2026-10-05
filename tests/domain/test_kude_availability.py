"""KuDE availability by document state (DECISIONES F51)."""

import pytest

from kilasifen.domain.documents.kude_availability import (
    is_kude_available,
    normalize_kude_status,
)


@pytest.mark.parametrize(
    "status",
    [
        "approved",
        "approved_with_observation",
        # Any approved variant counts as approved.
        "APPROVED_SOMETHING_NEW",
        # Validacion posterior: the KuDE may be delivered before approval
        # (MT v150 §6.2 p. 24).
        "queued",
        "processing",
        "submitting",
        "submitted",
        "retry_pending",
        " Reconciliation_Required ",
    ],
)
def test_kude_is_available_for_approved_and_pending_documents(status):
    assert is_kude_available(status)


@pytest.mark.parametrize(
    "status",
    [
        # MT v150 §6.4: a rejected DE never becomes a DTE.
        "rejected",
        "failed",
        # Dto 872/2023 Art. 30: a cancelled DTE loses its validity.
        "cancelled",
        # Dto 872/2023 Art. 31: an inutilized number has no DE.
        "inutilized",
        "INUTILIZED",
        # Unknown or empty states are refused instead of guessed.
        "draft",
        "",
        None,
    ],
)
def test_kude_is_refused_for_documents_that_are_not_a_valid_dte(status):
    assert not is_kude_available(status)


def test_status_is_normalized_for_the_error_details():
    assert normalize_kude_status(" Rejected ") == "rejected"
    assert normalize_kude_status(None) == ""
