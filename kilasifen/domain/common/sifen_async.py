"""SIFEN async decision rules and state machine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from kilasifen.domain.common.errors import DomainInvariantError


class AsyncOperation(str, Enum):
    """SIFEN async operations that emit response codes."""

    RECIBE_LOTE = "recibe_lote"
    CONSULTA_LOTE = "consulta_lote"
    CONSULTA_CDC = "consulta_cdc"


class AsyncState(str, Enum):
    """Internal states for async lot/document processing."""

    DRAFT = "draft"
    LOT_RECEIVED = "lot_received"
    LOT_NOT_QUEUED = "lot_not_queued"
    LOT_PROCESSING = "lot_processing"
    LOT_DONE = "lot_done"
    LOT_NOT_FOUND = "lot_not_found"
    LOT_QUERY_EXPIRED = "lot_query_expired"
    DE_APPROVED = "de_approved"
    DE_APPROVED_WITH_OBSERVATION = "de_approved_with_observation"
    DE_REJECTED = "de_rejected"
    DE_NOT_FOUND_OR_NOT_APPROVED = "de_not_found_or_not_approved"
    UNKNOWN = "unknown"


class AsyncAction(str, Enum):
    """Operational actions after one async response."""

    START_LOT_POLLING = "start_lot_polling"
    FIX_LOT_AND_RESUBMIT = "fix_lot_and_resubmit"
    POLL_LOT_AGAIN = "poll_lot_again"
    PARSE_LOT_RESULTS = "parse_lot_results"
    RECONCILE_BY_CDC = "reconcile_by_cdc"
    SWITCH_TO_CDC_QUERIES = "switch_to_cdc_queries"
    HOLD_AND_CHECK_LOT_BEFORE_RESEND = "hold_and_check_lot_before_resend"
    STORE_APPROVED_XML = "store_approved_xml"
    MANUAL_INVESTIGATION = "manual_investigation"


@dataclass(frozen=True, slots=True)
class AsyncDecision:
    """Normalized decision for one SIFEN async response."""

    operation: AsyncOperation
    code: str
    state: AsyncState
    action: AsyncAction
    terminal: bool
    should_retry: bool
    min_retry_delay_minutes: int | None


_RECIBE_LOTE_DECISIONS = {
    "0300": AsyncDecision(
        operation=AsyncOperation.RECIBE_LOTE,
        code="0300",
        state=AsyncState.LOT_RECEIVED,
        action=AsyncAction.START_LOT_POLLING,
        terminal=False,
        should_retry=True,
        min_retry_delay_minutes=10,
    ),
    "0301": AsyncDecision(
        operation=AsyncOperation.RECIBE_LOTE,
        code="0301",
        state=AsyncState.LOT_NOT_QUEUED,
        action=AsyncAction.FIX_LOT_AND_RESUBMIT,
        terminal=False,
        should_retry=False,
        min_retry_delay_minutes=None,
    ),
}


_CONSULTA_LOTE_DECISIONS = {
    "0360": AsyncDecision(
        operation=AsyncOperation.CONSULTA_LOTE,
        code="0360",
        state=AsyncState.LOT_NOT_FOUND,
        action=AsyncAction.RECONCILE_BY_CDC,
        terminal=False,
        should_retry=False,
        min_retry_delay_minutes=None,
    ),
    "0361": AsyncDecision(
        operation=AsyncOperation.CONSULTA_LOTE,
        code="0361",
        state=AsyncState.LOT_PROCESSING,
        action=AsyncAction.POLL_LOT_AGAIN,
        terminal=False,
        should_retry=True,
        min_retry_delay_minutes=10,
    ),
    "0362": AsyncDecision(
        operation=AsyncOperation.CONSULTA_LOTE,
        code="0362",
        state=AsyncState.LOT_DONE,
        action=AsyncAction.PARSE_LOT_RESULTS,
        terminal=False,
        should_retry=False,
        min_retry_delay_minutes=None,
    ),
    "0364": AsyncDecision(
        operation=AsyncOperation.CONSULTA_LOTE,
        code="0364",
        state=AsyncState.LOT_QUERY_EXPIRED,
        action=AsyncAction.SWITCH_TO_CDC_QUERIES,
        terminal=False,
        should_retry=False,
        min_retry_delay_minutes=None,
    ),
}


_CONSULTA_CDC_DECISIONS = {
    "0420": AsyncDecision(
        operation=AsyncOperation.CONSULTA_CDC,
        code="0420",
        state=AsyncState.DE_NOT_FOUND_OR_NOT_APPROVED,
        action=AsyncAction.HOLD_AND_CHECK_LOT_BEFORE_RESEND,
        terminal=False,
        should_retry=False,
        min_retry_delay_minutes=None,
    ),
    "0422": AsyncDecision(
        operation=AsyncOperation.CONSULTA_CDC,
        code="0422",
        state=AsyncState.DE_APPROVED,
        action=AsyncAction.STORE_APPROVED_XML,
        terminal=True,
        should_retry=False,
        min_retry_delay_minutes=None,
    ),
}


def decide_async(operation: AsyncOperation, code: str) -> AsyncDecision:
    """Map one SIFEN async code into a normalized internal decision."""

    if operation == AsyncOperation.RECIBE_LOTE:
        decision = _RECIBE_LOTE_DECISIONS.get(code)
    elif operation == AsyncOperation.CONSULTA_LOTE:
        decision = _CONSULTA_LOTE_DECISIONS.get(code)
    else:
        decision = _CONSULTA_CDC_DECISIONS.get(code)

    if decision is not None:
        return decision

    return AsyncDecision(
        operation=operation,
        code=code,
        state=AsyncState.UNKNOWN,
        action=AsyncAction.MANUAL_INVESTIGATION,
        terminal=False,
        should_retry=False,
        min_retry_delay_minutes=None,
    )


def transition_async(
    current_state: AsyncState,
    *,
    operation: AsyncOperation,
    code: str,
) -> AsyncDecision:
    """Validate and return the next decision for one async response."""

    decision = decide_async(operation, code)
    allowed = _ALLOWED_TRANSITIONS.get(current_state, set())
    if decision.state not in allowed:
        raise DomainInvariantError(
            f"Invalid async transition from {current_state.value} "
            f"to {decision.state.value} for {operation.value}:{code}"
        )
    return decision


def map_lot_detail_status(raw_status: str) -> AsyncState:
    """Map gResProcLote.dEstRes text into an internal final DE state."""

    status = (raw_status or "").strip().lower()
    if "aprobado con observ" in status:
        return AsyncState.DE_APPROVED_WITH_OBSERVATION
    if "aprobado" in status:
        return AsyncState.DE_APPROVED
    if "rechazado" in status:
        return AsyncState.DE_REJECTED
    return AsyncState.UNKNOWN


def is_definitive_document_state(state: AsyncState) -> bool:
    """Return True when a DE has definitive SIFEN outcome."""

    return state in {
        AsyncState.DE_APPROVED,
        AsyncState.DE_APPROVED_WITH_OBSERVATION,
        AsyncState.DE_REJECTED,
    }


def can_resend_same_cdc(state: AsyncState) -> bool:
    """Enforce anti-duplicate rule: resend only after definitive SIFEN outcome."""

    return is_definitive_document_state(state)


_ALLOWED_TRANSITIONS: dict[AsyncState, set[AsyncState]] = {
    AsyncState.DRAFT: {
        AsyncState.LOT_RECEIVED,
        AsyncState.LOT_NOT_QUEUED,
        AsyncState.UNKNOWN,
    },
    AsyncState.LOT_NOT_QUEUED: {
        AsyncState.LOT_RECEIVED,
        AsyncState.LOT_NOT_QUEUED,
        AsyncState.UNKNOWN,
    },
    AsyncState.LOT_RECEIVED: {
        AsyncState.LOT_PROCESSING,
        AsyncState.LOT_DONE,
        AsyncState.LOT_NOT_FOUND,
        AsyncState.LOT_QUERY_EXPIRED,
        AsyncState.UNKNOWN,
    },
    AsyncState.LOT_PROCESSING: {
        AsyncState.LOT_PROCESSING,
        AsyncState.LOT_DONE,
        AsyncState.LOT_QUERY_EXPIRED,
        AsyncState.UNKNOWN,
    },
    AsyncState.LOT_DONE: {
        AsyncState.DE_APPROVED,
        AsyncState.DE_NOT_FOUND_OR_NOT_APPROVED,
        AsyncState.UNKNOWN,
    },
    AsyncState.LOT_QUERY_EXPIRED: {
        AsyncState.DE_APPROVED,
        AsyncState.DE_NOT_FOUND_OR_NOT_APPROVED,
        AsyncState.UNKNOWN,
    },
    AsyncState.LOT_NOT_FOUND: {
        AsyncState.DE_APPROVED,
        AsyncState.DE_NOT_FOUND_OR_NOT_APPROVED,
        AsyncState.UNKNOWN,
    },
    AsyncState.DE_NOT_FOUND_OR_NOT_APPROVED: {
        AsyncState.DE_NOT_FOUND_OR_NOT_APPROVED,
        AsyncState.DE_APPROVED,
        AsyncState.UNKNOWN,
    },
    AsyncState.DE_APPROVED: {
        AsyncState.DE_APPROVED,
        AsyncState.UNKNOWN,
    },
    AsyncState.DE_APPROVED_WITH_OBSERVATION: {
        AsyncState.DE_APPROVED_WITH_OBSERVATION,
        AsyncState.UNKNOWN,
    },
    AsyncState.DE_REJECTED: {
        AsyncState.DE_REJECTED,
        AsyncState.UNKNOWN,
    },
    AsyncState.UNKNOWN: {
        AsyncState.UNKNOWN,
    },
}
