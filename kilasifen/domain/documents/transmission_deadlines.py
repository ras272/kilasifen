"""Transmission deadlines of a DE that SIFEN has not approved yet.

- A DE must reach SIFEN within 72 h of its declared signature time
  (``dFecFirma``); later it is approved with observation 1005, an
  extemporaneous transmission with possible sanctions (Dto 872/2023 Art. 27;
  MT v150 §6.2 pp. 24-25 and §12.4 val. 6 p. 159; RG 23/2019 Art. 18).
- A DE whose emission date (``dFeEmiDE``) is more than 720 h before the
  transmission is rejected with 1150 (MT v150 §12.4 val. 19 p. 162; RG
  23/2019 Art. 13).

While a document waits for a resend or a reconciliation the platform raises
alerts some time before each limit (DECISIONES F63). The lead time is a
platform choice, not a regulation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

NORMAL_TRANSMISSION_WINDOW = timedelta(hours=72)
EMISSION_REJECTION_WINDOW = timedelta(hours=720)
ALERT_LEAD_TIME = timedelta(hours=24)


class DeadlineAlert(str, Enum):
    """Alerts about the transmission deadlines of a pending DE."""

    LATE_TRANSMISSION_SOON = "late_transmission_soon"
    """Less than :data:`ALERT_LEAD_TIME` left of the 72 h after dFecFirma."""

    LATE_TRANSMISSION = "late_transmission"
    """The 72 h passed: an approval will carry observation 1005."""

    EMISSION_REJECTION_SOON = "emission_rejection_soon"
    """Less than :data:`ALERT_LEAD_TIME` left of the 720 h after dFeEmiDE."""

    EMISSION_REJECTION = "emission_rejection"
    """The 720 h passed: SIFEN rejects the DE with 1150."""


def transmission_deadline_alerts(
    *,
    signed_at: datetime | None,
    issued_at: datetime | None,
    now: datetime,
) -> tuple[DeadlineAlert, ...]:
    """Alerts that apply ``now`` to a DE signed and issued at those times.

    All datetimes must be timezone aware. A missing time raises no alert.
    """

    alerts: list[DeadlineAlert] = []
    if signed_at is not None:
        alerts.extend(
            _alerts_for(
                limit=signed_at + NORMAL_TRANSMISSION_WINDOW,
                now=now,
                soon=DeadlineAlert.LATE_TRANSMISSION_SOON,
                passed=DeadlineAlert.LATE_TRANSMISSION,
            )
        )
    if issued_at is not None:
        alerts.extend(
            _alerts_for(
                limit=issued_at + EMISSION_REJECTION_WINDOW,
                now=now,
                soon=DeadlineAlert.EMISSION_REJECTION_SOON,
                passed=DeadlineAlert.EMISSION_REJECTION,
            )
        )
    return tuple(alerts)


def _alerts_for(
    *,
    limit: datetime,
    now: datetime,
    soon: DeadlineAlert,
    passed: DeadlineAlert,
) -> list[DeadlineAlert]:
    if now >= limit:
        return [passed]
    if now >= limit - ALERT_LEAD_TIME:
        return [soon]
    return []
