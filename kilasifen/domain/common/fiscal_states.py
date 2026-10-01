"""Canonical fiscal document and job state rules."""

from __future__ import annotations

DOCUMENT_APPROVED_STATUSES = frozenset({"approved", "approved_with_observation"})

#: The exact request is persisted and a worker is sending it to SIFEN. A
#: document still in this state after its worker died may or may not have
#: reached SIFEN.
DOCUMENT_SUBMITTING_STATUS = "submitting"

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

#: Pending states in which SIFEN may already hold the document. They are
#: resolved by querying the CDC, never by sending the document again.
DOCUMENT_POSSIBLY_RECEIVED_STATUSES = frozenset(
    {
        DOCUMENT_SUBMITTING_STATUS,
        "submitted",
        "retry_pending",
        "reconciliation_required",
    }
)
DOCUMENT_TERMINAL_STATUSES = frozenset(
    {*DOCUMENT_APPROVED_STATUSES, "rejected", "failed", "cancelled"}
)


def normalize_document_status(status: str | None) -> str:
    """Normalize one SIFEN/application status without guessing approval."""

    normalized = str(status or "").strip().lower()
    return normalized or "submitted"


def job_status_for_document(document_status: str) -> str:
    """Map a fiscal document state to its durable orchestration state."""

    normalized = normalize_document_status(document_status)
    if normalized in DOCUMENT_APPROVED_STATUSES:
        return "succeeded"
    if normalized in {"rejected", "failed", "cancelled"}:
        return "failed"
    return "retry_scheduled"


def require_document_transition(current: str, target: str) -> str:
    """Reject changes away from a terminal fiscal state."""

    current_status = normalize_document_status(current)
    target_status = normalize_document_status(target)
    if current_status in DOCUMENT_TERMINAL_STATUSES and target_status != current_status:
        raise ValueError(
            f"invalid terminal document transition: {current_status} -> {target_status}"
        )
    return target_status
