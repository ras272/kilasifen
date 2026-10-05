from datetime import date, datetime, timedelta, timezone

import pytest

from kilasifen.domain.common.paraguay_time import PARAGUAY_TZ
from kilasifen.domain.documents.fiscal_dates import (
    EMISSION_BEFORE_SIFEN,
    EMISSION_FAR_FROM_TRANSMISSION,
    EMISSION_TOO_FAR_AHEAD,
    EMISSION_TOO_OLD,
    LATE_AFTER_SIGNATURE,
    SIGNATURE_IN_THE_FUTURE,
    emission_window_error,
    parse_sifen_datetime,
    signature_time_error,
    transmission_warnings,
)

_NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=PARAGUAY_TZ)
_WALL_NOW = datetime(2026, 10, 1, 12, 0, 0)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-04-26T23:21:14-03:00", datetime(2026, 4, 26, 23, 21, 14)),
        ("2026-04-27T02:21:14Z", datetime(2026, 4, 26, 23, 21, 14)),
        ("2026-04-26T23:21:14", datetime(2026, 4, 26, 23, 21, 14)),
        ("2026-04-26", datetime(2026, 4, 26, 0, 0, 0)),
        (date(2026, 4, 26), datetime(2026, 4, 26, 0, 0, 0)),
        (
            datetime(2026, 4, 27, 2, 21, 14, tzinfo=timezone.utc),
            datetime(2026, 4, 26, 23, 21, 14),
        ),
    ],
)
def test_dates_are_read_as_paraguayan_wall_time(raw, expected: datetime) -> None:
    assert parse_sifen_datetime(raw) == expected


def test_unreadable_date_raises_value_error() -> None:
    with pytest.raises(ValueError):
        parse_sifen_datetime("25/04/2026")


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (timedelta(hours=-720), None),  # exactly 720 h late: still accepted
        (timedelta(hours=-720, seconds=-1), EMISSION_TOO_OLD),  # 1150
        (timedelta(hours=120), None),  # exactly 120 h ahead: still accepted
        (timedelta(hours=120, seconds=1), EMISSION_TOO_FAR_AHEAD),  # 1151
        (timedelta(0), None),
    ],
)
def test_emission_window_matches_1150_and_1151(offset, expected) -> None:
    assert emission_window_error(_WALL_NOW + offset, _NOW) == expected


def test_emission_must_be_after_the_sifen_launch() -> None:
    # 1156: "debe ser posterior al 22 de noviembre del 2018".
    launch_day = datetime(2018, 11, 22, 23, 0, 0)
    now = datetime(2018, 11, 23, 1, 0, 0, tzinfo=PARAGUAY_TZ)

    assert emission_window_error(launch_day, now) == EMISSION_BEFORE_SIFEN


def test_signature_cannot_be_after_now() -> None:
    assert signature_time_error(_WALL_NOW, _NOW) is None
    assert (
        signature_time_error(_WALL_NOW + timedelta(seconds=1), _NOW)
        == SIGNATURE_IN_THE_FUTURE
    )


def test_transmission_is_normal_inside_72_and_120_hours() -> None:
    assert (
        transmission_warnings(
            emission=_WALL_NOW - timedelta(hours=100),
            signed_at=_WALL_NOW - timedelta(hours=72),
            now=_NOW,
        )
        == []
    )


def test_transmission_late_after_signature_or_far_from_emission_warns() -> None:
    warnings = transmission_warnings(
        emission=_WALL_NOW - timedelta(hours=121),
        signed_at=_WALL_NOW - timedelta(hours=73),
        now=_NOW,
    )

    assert warnings == [LATE_AFTER_SIGNATURE, EMISSION_FAR_FROM_TRANSMISSION]


def test_unsigned_document_only_checks_the_emission_distance() -> None:
    emission = _WALL_NOW - timedelta(hours=200)

    assert transmission_warnings(emission=emission, now=_NOW) == [
        EMISSION_FAR_FROM_TRANSMISSION
    ]
