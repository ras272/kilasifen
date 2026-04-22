"""Polling helpers for async SIFEN workflows."""
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic, sleep
from typing import Any, Callable

from pysifen.sdk.errors import SifenTimeoutError


@dataclass(frozen=True)
class PollingConfig:
    """Configurable polling behavior with safe defaults."""

    interval_seconds: float = 2.0
    timeout_seconds: float = 120.0
    max_attempts: None | int = 60

    def __post_init__(self):
        if self.interval_seconds < 0:
            raise ValueError("interval_seconds must be >= 0")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")
        if self.max_attempts is not None and self.max_attempts <= 0:
            raise ValueError("max_attempts must be > 0")


def poll_lote_status(
    consultar_lote: Callable[[Any], Any],
    prot_lote: Any,
    config: PollingConfig = PollingConfig(),
    pending_codes: tuple[str, ...] = ("0300", "0360"),
):
    """Poll lote status until terminal state or timeout.

    A status is considered pending only if ``dCodResLot`` matches
    ``pending_codes``. Unknown or missing codes stop immediately.
    """

    started_at = monotonic()
    attempts = 0

    while True:
        response = consultar_lote(prot_lote)
        code = str(getattr(response, "dCodResLot", "") or "").strip()

        if not code or code not in pending_codes:
            return response

        attempts += 1
        if config.max_attempts is not None and attempts >= config.max_attempts:
            raise SifenTimeoutError(
                "Polling timeout while waiting lote status."
            )
        if monotonic() - started_at >= config.timeout_seconds:
            raise SifenTimeoutError(
                "Polling timeout while waiting lote status."
            )
        if config.interval_seconds > 0:
            sleep(config.interval_seconds)


def poll_dte_async_status(
    fetch_status: Callable[[str], Any],
    protocol_id: str,
    config: PollingConfig = PollingConfig(),
    pending_tokens: tuple[str, ...] = (
        "PENDIENTE",
        "EN PROCESO",
        "PROCESANDO",
    ),
):
    """Poll async DTE result until terminal state or timeout.

    The default behavior is:
    - success when ``rConsDte`` payload exists;
    - pending when message contains one of ``pending_tokens``;
    - terminal for unknown/missing messages to avoid infinite loops.
    """

    started_at = monotonic()
    attempts = 0

    while True:
        response = fetch_status(protocol_id)
        payload = getattr(response, "rConsDte", None)
        if payload:
            return response

        msg = str(getattr(response, "dMsgRes", "") or "").upper()
        if not msg or not any(token in msg for token in pending_tokens):
            return response

        attempts += 1
        if config.max_attempts is not None and attempts >= config.max_attempts:
            raise SifenTimeoutError(
                "Polling timeout while waiting DTE async result."
            )
        if monotonic() - started_at >= config.timeout_seconds:
            raise SifenTimeoutError(
                "Polling timeout while waiting DTE async result."
            )
        if config.interval_seconds > 0:
            sleep(config.interval_seconds)
