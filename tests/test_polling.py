"""Tests for polling helpers."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from kilasifen.engine.sdk.errors import SifenTimeoutError
from kilasifen.engine.sdk.polling import (
    PollingConfig,
    poll_dte_async_status,
    poll_lote_status,
)


@dataclass
class LoteResponse:
    dCodResLot: str
    dMsgResLot: str = ""


@dataclass
class DteResponse:
    dMsgRes: str
    rConsDte: bytes | None = None


def test_poll_lote_status_retries_until_terminal():
    calls = {"n": 0}

    def consultar_lote(_prot):
        calls["n"] += 1
        if calls["n"] == 1:
            return LoteResponse(dCodResLot="0300")
        return LoteResponse(dCodResLot="0362")

    result = poll_lote_status(
        consultar_lote,
        prot_lote=123,
        config=PollingConfig(interval_seconds=0, max_attempts=5),
    )

    assert result.dCodResLot == "0362"
    assert calls["n"] == 2


def test_poll_lote_status_times_out():
    def consultar_lote(_prot):
        return LoteResponse(dCodResLot="0300")

    with pytest.raises(SifenTimeoutError):
        poll_lote_status(
            consultar_lote,
            prot_lote=123,
            config=PollingConfig(
                interval_seconds=0,
                timeout_seconds=1,
                max_attempts=3,
            ),
        )


def test_poll_dte_async_status_retries_until_payload():
    calls = {"n": 0}

    def fetch_status(_protocol_id):
        calls["n"] += 1
        if calls["n"] == 1:
            return DteResponse(dMsgRes="Pendiente de procesamiento")
        return DteResponse(dMsgRes="Disponible", rConsDte=b"zip-data")

    result = poll_dte_async_status(
        fetch_status,
        protocol_id="ABC123",
        config=PollingConfig(interval_seconds=0, max_attempts=5),
    )

    assert result.rConsDte == b"zip-data"
    assert calls["n"] == 2


def test_poll_dte_async_status_stops_on_non_pending_message():
    def fetch_status(_protocol_id):
        return DteResponse(dMsgRes="Error de consulta")

    result = poll_dte_async_status(
        fetch_status,
        protocol_id="ABC123",
        config=PollingConfig(interval_seconds=0, max_attempts=5),
    )

    assert result.dMsgRes == "Error de consulta"
    assert result.rConsDte is None


def test_poll_dte_async_status_times_out():
    def fetch_status(_protocol_id):
        return DteResponse(dMsgRes="En proceso")

    with pytest.raises(SifenTimeoutError):
        poll_dte_async_status(
            fetch_status,
            protocol_id="ABC123",
            config=PollingConfig(
                interval_seconds=0,
                timeout_seconds=1,
                max_attempts=2,
            ),
        )
