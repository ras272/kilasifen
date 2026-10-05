"""Official Paraguayan time for fiscal date fields.

SIFEN date fields (``dFeEmiDE``, ``dFecFirma``, event dates) carry no time
zone: they are wall-clock values in the official time of Paraguay, checked
against the SIFEN clock (MT v150 control de versiones v140 p. 11, XSD
``fecHhmmss``; validations 1004, 1150 and 1151).

Since the first Sunday of October 2024 that official time is UTC-03:00 all
year round, with no daylight saving time (Ley 7354/2024 arts. 1-2). A fixed
offset is used instead of ``ZoneInfo("America/Asuncion")`` so the result does
not depend on the tzdata release installed on the host.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

#: Official time of Paraguay (Ley 7354/2024): UTC-03:00, without DST.
PARAGUAY_TZ = timezone(timedelta(hours=-3), "PYT")

#: Text layout of SIFEN date-time fields (XSD ``fecHhmmss``).
SIFEN_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"


def paraguay_now() -> datetime:
    """Return the current instant as an aware datetime in Paraguayan time."""

    return datetime.now(PARAGUAY_TZ)


def to_paraguay_wall_time(value: datetime) -> datetime:
    """Return ``value`` as a naive Paraguayan wall-clock time, in seconds.

    A naive ``value`` is taken as already expressed in Paraguayan time.
    """

    if value.tzinfo is not None:
        value = value.astimezone(PARAGUAY_TZ).replace(tzinfo=None)
    return value.replace(microsecond=0)


def format_sifen_datetime(value: datetime) -> str:
    """Format ``value`` as a SIFEN date-time (``AAAA-MM-DDThh:mm:ss``)."""

    return to_paraguay_wall_time(value).strftime(SIFEN_DATETIME_FORMAT)
