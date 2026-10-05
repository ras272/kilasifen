from datetime import datetime, timedelta, timezone

from kilasifen.domain.common.paraguay_time import (
    PARAGUAY_TZ,
    format_sifen_datetime,
    paraguay_now,
    to_paraguay_wall_time,
)


def test_paraguay_time_is_a_fixed_utc_minus_three_offset() -> None:
    # Ley 7354/2024: UTC-3 all year. A July instant used to be UTC-4 (DST off)
    # under the old rules; the fixed offset must not depend on tzdata.
    july_utc = datetime(2026, 7, 15, 13, 0, 0, tzinfo=timezone.utc)
    january_utc = datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc)

    assert PARAGUAY_TZ.utcoffset(None) == timedelta(hours=-3)
    assert to_paraguay_wall_time(july_utc) == datetime(2026, 7, 15, 10, 0, 0)
    assert to_paraguay_wall_time(january_utc) == datetime(2026, 1, 15, 10, 0, 0)


def test_wall_time_keeps_naive_values_and_drops_microseconds() -> None:
    naive = datetime(2026, 4, 25, 10, 0, 0, 987654)

    assert to_paraguay_wall_time(naive) == datetime(2026, 4, 25, 10, 0, 0)


def test_sifen_datetime_format_has_no_zone() -> None:
    value = datetime(2026, 4, 27, 2, 21, 14, tzinfo=timezone.utc)

    assert format_sifen_datetime(value) == "2026-04-26T23:21:14"


def test_paraguay_now_is_aware_in_paraguayan_time() -> None:
    now = paraguay_now()

    assert now.utcoffset() == timedelta(hours=-3)
