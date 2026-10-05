"""Canonical fiscal document and job state rules."""

from __future__ import annotations

DOCUMENT_APPROVED_STATUSES = frozenset({"approved", "approved_with_observation"})

#: The exact request is persisted and a worker is sending it to SIFEN. A
#: document still in this state after its worker died may or may not have
#: reached SIFEN.
DOCUMENT_SUBMITTING_STATUS = "submitting"

#: The DTE was cancelled with an approved cancellation event (Dto 872/2023
#: Art. 30). Terminal.
DOCUMENT_CANCELLED_STATUS = "cancelled"

#: The document number was inutilized with an approved inutilization event
#: (MT v150 §11.1.1 p. 112; Dto 872/2023 Arts. 29 and 31). Terminal: a DE
#: with that number would be rejected with 1109 (MT v150 §12.4 C007 p. 161).
DOCUMENT_INUTILIZED_STATUS = "inutilized"

DOCUMENT_PENDING_STATUSES = frozenset(
    {
        "queued",
        "processing",
        DOCUMENT_SUBMITTING_STATUS,
        "submitted",
        "retry_pending",
        "reconciliation_required",
    }
)

#: Pending states in which SIFEN may already hold the document. The next
#: step is always a query by CDC; the document is only sent again once SIFEN
#: answered that the CDC is not approved (0420).
DOCUMENT_POSSIBLY_RECEIVED_STATUSES = frozenset(
    {
        DOCUMENT_SUBMITTING_STATUS,
        "submitted",
        "retry_pending",
        "reconciliation_required",
    }
)
DOCUMENT_TERMINAL_STATUSES = frozenset(
    {
        *DOCUMENT_APPROVED_STATUSES,
        "rejected",
        "failed",
        DOCUMENT_CANCELLED_STATUS,
        DOCUMENT_INUTILIZED_STATUS,
    }
)

#: The only ways out of a terminal state that the regulation provides:
#: an approved DTE can be cancelled (Dto 872/2023 Art. 30); a rejected DE can
#: be sent again with the same CDC or its number inutilized (Dto 872/2023
#: Art. 29; MT v150 §6.5 pp. 26-27); a DE that never reached SIFEN can be sent
#: again or its number inutilized (Dto 872/2023 Art. 31). Cancelled and
#: inutilized are final (Dto 872/2023 Art. 30).
_TERMINAL_EXITS: dict[str, frozenset[str]] = {
    "approved": frozenset({DOCUMENT_CANCELLED_STATUS}),
    "approved_with_observation": frozenset({DOCUMENT_CANCELLED_STATUS}),
    "rejected": frozenset({DOCUMENT_SUBMITTING_STATUS, DOCUMENT_INUTILIZED_STATUS}),
    "failed": frozenset(
        {"queued", DOCUMENT_SUBMITTING_STATUS, DOCUMENT_INUTILIZED_STATUS}
    ),
}


def normalize_document_status(status: str | None) -> str:
    """Normalize one SIFEN/application status without guessing approval."""

    normalized = str(status or "").strip().lower()
    return normalized or "submitted"


def job_status_for_document(document_status: str) -> str:
    """Map a fiscal document state to its durable orchestration state."""

    normalized = normalize_document_status(document_status)
    if normalized in DOCUMENT_APPROVED_STATUSES:
        return "succeeded"
    if normalized in DOCUMENT_TERMINAL_STATUSES:
        return "failed"
    return "retry_scheduled"


def require_document_transition(current: str, target: str) -> str:
    """Reject changes away from a terminal fiscal state the rules do not allow."""

    current_status = normalize_document_status(current)
    target_status = normalize_document_status(target)
    if (
        current_status in DOCUMENT_TERMINAL_STATUSES
        and target_status != current_status
        and target_status not in _TERMINAL_EXITS.get(current_status, frozenset())
    ):
        raise ValueError(
            f"invalid terminal document transition: {current_status} -> {target_status}"
        )
    return target_status
