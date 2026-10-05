"""Time rules of a DE: emission window, signing time and transmission term.

All values are naive Paraguayan wall-clock times (see
:mod:`kilasifen.domain.common.paraguay_time`); ``now`` may be aware.

- ``dFeEmiDE`` (D002) may be up to 720 hours (30 days) before the transmission
  (1150) and up to 120 hours (5 days) after it (1151), and must be after
  22 November 2018 (1156). MT v150 D002 p. 65 and §12.4 p. 162; RG 23/2019
  Art. 13.
- ``dFecFirma`` (A004) is the real time of the signature and cannot be after
  the SIFEN clock (1004). MT v150 A004 p. 62 and p. 159; RG 23/2019 Art. 13.
- A transmission is normal within 72 hours of the declared signature and
  with less than 120 hours between emission and transmission; otherwise it is
  approved with observation 1005 (extemporaneous, with sanctions). MT v150
  §6.2/§6.2.1 pp. 24-25; Decreto 872/2023 Art. 27; RG 23/2019 Art. 18.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from kilasifen.domain.common.paraguay_time import to_paraguay_wall_time

MAX_EMISSION_DELAY = timedelta(hours=720)
MAX_EMISSION_ADVANCE = timedelta(hours=120)
#: 1156: "debe ser posterior al 22 de noviembre del 2018".
SIFEN_LAUNCH_DATE = date(2018, 11, 22)
NORMAL_TRANSMISSION_AFTER_SIGNATURE = timedelta(hours=72)
NORMAL_EMISSION_DISTANCE = timedelta(hours=120)

EMISSION_TOO_OLD = "documents.fecha_emision.too_old"
EMISSION_TOO_FAR_AHEAD = "documents.fecha_emision.too_far_ahead"
EMISSION_BEFORE_SIFEN = "documents.fecha_emision.before_sifen_launch"
SIGNATURE_IN_THE_FUTURE = "documents.fecha_firma.after_now"
LATE_AFTER_SIGNATURE = "documents.transmission.late_after_signature"
EMISSION_FAR_FROM_TRANSMISSION = "documents.transmission.emission_far_from_now"


def parse_sifen_datetime(raw: object) -> datetime:
    """Parse a payload or XML date into a naive Paraguayan wall time.

    Accepts ``datetime``, ``date`` (taken at 00:00:00) and ISO 8601 text with
    or without offset (a ``Z`` suffix included). Raises ``ValueError``.
    """

    if isinstance(raw, datetime):
        value = raw
    elif isinstance(raw, date):
        value = datetime.combine(raw, time(0, 0, 0))
    else:
        text = str(raw).strip()
        if text.endswith(("Z", "z")):
            # Python < 3.11 fromisoformat does not accept the "Z" suffix.
            text = text[:-1] + "+00:00"
        try:
            value = datetime.fromisoformat(text)
        except ValueError:
            value = datetime.combine(date.fromisoformat(text), time(0, 0, 0))
    return to_paraguay_wall_time(value)


def emission_window_error(emission: datetime, now: datetime) -> str | None:
    """Return the code of the rule ``emission`` breaks at ``now``, if any."""

    current = to_paraguay_wall_time(now)
    if emission.date() <= SIFEN_LAUNCH_DATE:
        return EMISSION_BEFORE_SIFEN
    if current - emission > MAX_EMISSION_DELAY:
        return EMISSION_TOO_OLD
    if emission - current > MAX_EMISSION_ADVANCE:
        return EMISSION_TOO_FAR_AHEAD
    return None


def signature_time_error(signed_at: datetime, now: datetime) -> str | None:
    """1004: the declared signing time cannot be after the current time."""

    if signed_at > to_paraguay_wall_time(now):
        return SIGNATURE_IN_THE_FUTURE
    return None


def transmission_warnings(
    *,
    emission: datetime,
    now: datetime,
    signed_at: datetime | None = None,
) -> list[str]:
    """Return why a transmission at ``now`` would be extemporaneous (1005).

    Without ``signed_at`` (the document is not signed yet) the signature is
    assumed to happen at ``now``.
    """

    current = to_paraguay_wall_time(now)
    warnings = []
    late = NORMAL_TRANSMISSION_AFTER_SIGNATURE
    if signed_at is not None and current - signed_at > late:
        warnings.append(LATE_AFTER_SIGNATURE)
    if abs(current - emission) > NORMAL_EMISSION_DISTANCE:
        warnings.append(EMISSION_FAR_FROM_TRANSMISSION)
    return warnings
