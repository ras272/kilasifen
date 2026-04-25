import pytest

from kilasifen.domain.common.errors import DomainInvariantError
from kilasifen.domain.common.sifen_async import (
    AsyncAction,
    AsyncOperation,
    AsyncState,
    can_resend_same_cdc,
    decide_async,
    map_lot_detail_status,
    transition_async,
)


def test_decide_async_maps_known_codes() -> None:
    receive = decide_async(AsyncOperation.RECIBE_LOTE, "0300")
    assert receive.state == AsyncState.LOT_RECEIVED
    assert receive.action == AsyncAction.START_LOT_POLLING
    assert receive.min_retry_delay_minutes == 10

    poll = decide_async(AsyncOperation.CONSULTA_LOTE, "0361")
    assert poll.state == AsyncState.LOT_PROCESSING
    assert poll.action == AsyncAction.POLL_LOT_AGAIN
    assert poll.should_retry is True

    cdc = decide_async(AsyncOperation.CONSULTA_CDC, "0422")
    assert cdc.state == AsyncState.DE_APPROVED
    assert cdc.action == AsyncAction.STORE_APPROVED_XML
    assert cdc.terminal is True


def test_decide_async_unknown_code_returns_manual_investigation() -> None:
    decision = decide_async(AsyncOperation.CONSULTA_LOTE, "9999")
    assert decision.state == AsyncState.UNKNOWN
    assert decision.action == AsyncAction.MANUAL_INVESTIGATION
    assert decision.should_retry is False


def test_transition_async_enforces_valid_state_progression() -> None:
    transition = transition_async(
        AsyncState.DRAFT,
        operation=AsyncOperation.RECIBE_LOTE,
        code="0300",
    )
    assert transition.state == AsyncState.LOT_RECEIVED

    with pytest.raises(DomainInvariantError):
        transition_async(
            AsyncState.DRAFT,
            operation=AsyncOperation.CONSULTA_LOTE,
            code="0361",
        )


@pytest.mark.parametrize(
    ("raw_status", "expected"),
    [
        ("Aprobado", AsyncState.DE_APPROVED),
        ("Aprobado con Observacion", AsyncState.DE_APPROVED_WITH_OBSERVATION),
        ("Rechazado", AsyncState.DE_REJECTED),
        ("", AsyncState.UNKNOWN),
    ],
)
def test_map_lot_detail_status(raw_status: str, expected: AsyncState) -> None:
    assert map_lot_detail_status(raw_status) == expected


def test_can_resend_same_cdc_only_after_definitive_status() -> None:
    assert can_resend_same_cdc(AsyncState.LOT_PROCESSING) is False
    assert can_resend_same_cdc(AsyncState.DE_NOT_FOUND_OR_NOT_APPROVED) is False
    assert can_resend_same_cdc(AsyncState.DE_REJECTED) is True
