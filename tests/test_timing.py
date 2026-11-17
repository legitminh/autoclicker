from datetime import UTC, date, datetime
from threading import Event
from time import time_ns
from zoneinfo import ZoneInfo

import pytest

from autoclicker.timing import (
    ScheduledClick,
    epoch_ns,
    local_candidates,
    nearest_minute,
    relative_text,
    wait_until,
)

NY = ZoneInfo("America/New_York")


@pytest.mark.parametrize(
    ("second", "microsecond", "minute"), [(29, 999999, 12), (30, 0, 13), (59, 999999, 13)]
)
def test_rounding(second, microsecond, minute):
    result = nearest_minute(datetime(2026, 11, 17, 14, 12, second, microsecond, tzinfo=NY))
    assert (result.hour, result.minute, result.second, result.microsecond) == (14, minute, 0, 0)


def test_rounding_midnight():
    assert nearest_minute(datetime(2026, 12, 31, 23, 59, 40, tzinfo=NY)) == datetime(
        2027, 1, 1, tzinfo=NY
    )


def test_rounding_spring_forward():
    assert nearest_minute(datetime(2026, 3, 8, 1, 59, 40, tzinfo=NY)) == datetime(
        2026, 3, 8, 3, 0, tzinfo=NY
    )


def test_rounding_fall_back():
    result = nearest_minute(datetime(2026, 11, 1, 1, 59, 40, tzinfo=NY))
    assert (result.hour, result.minute, result.fold) == (1, 0, 1)


def test_days_milliseconds_and_local_zone():
    [target] = local_candidates(date(2026, 11, 17), 123, 15, 4, 3, 251, NY)
    assert target.date() == date(2027, 3, 20)
    assert target.microsecond == 251000
    assert target.utcoffset().total_seconds() == -4 * 3600


def test_gap_rejected():
    with pytest.raises(ValueError, match="does not exist"):
        local_candidates(date(2026, 3, 8), 0, 2, 30, 0, 0, NY)


def test_repeated_hour_has_two_distinct_instants():
    earlier, later = local_candidates(date(2026, 11, 1), 0, 1, 30, 0, 123, NY)
    assert epoch_ns(later) - epoch_ns(earlier) == 3600 * 1_000_000_000
    assert (earlier.fold, later.fold) == (0, 1)


@pytest.mark.parametrize(
    "values",
    [
        (-1, 12, 0, 0, 0),
        (10000, 12, 0, 0, 0),
        (0, 24, 0, 0, 0),
        (0, 0, 60, 0, 0),
        (0, 0, 0, 60, 0),
        (0, 0, 0, 0, 1000),
    ],
)
def test_invalid_fields(values):
    with pytest.raises(ValueError):
        local_candidates(date(2026, 11, 17), *values, NY)


def test_epoch_and_relative_duration():
    assert epoch_ns(datetime(1970, 1, 1, 0, 0, 0, 123000, tzinfo=UTC)) == 123_000_000
    assert relative_text(90_061_123_000_000) == "In 1d 01:01:01.123"
    assert relative_text(-1_234_000_000) == "0d 00:00:01.234 ago"


def test_wait_tracks_wall_clock_changes_and_never_returns_early():
    times = iter([0, 5_000_000_000, 2_000_000_000, 10_000_000_000])
    waited = []

    class FakeEvent:
        def is_set(self):
            return False

        def wait(self, seconds):
            waited.append(seconds)

    assert wait_until(10_000_000_000, FakeEvent(), lambda: next(times))
    assert len(waited) == 3
    assert all(0 < value <= 0.1 for value in waited)


def test_cancelled_wait():
    cancelled = Event()
    cancelled.set()
    assert not wait_until(time_ns() + 10_000_000_000, cancelled)


def test_worker_clicks_exactly_once_at_or_after_deadline():
    clicks, errors = [], []
    done = Event()
    deadline = time_ns() + 30_000_000
    job = ScheduledClick(deadline, lambda: clicks.append(time_ns()), done.set, errors.append)
    job.start()
    assert done.wait(2)
    job.join(1)
    assert len(clicks) == 1
    assert clicks[0] >= deadline
    assert errors == []


def test_worker_cancel_prevents_click():
    clicks = []
    job = ScheduledClick(time_ns() + 60_000_000_000, lambda: clicks.append(1), lambda: None, str)
    job.start()
    job.cancel()
    job.join(1)
    assert not job.is_alive()
    assert clicks == []


def test_worker_reports_failure_without_retrying():
    errors, clicks, completed = [], [], []

    def broken_click():
        clicks.append(1)
        raise RuntimeError("permission removed")

    job = ScheduledClick(time_ns(), broken_click, lambda: completed.append(1), errors.append)
    job.start()
    job.join(1)
    assert errors == ["permission removed"]
    assert clicks == [1]
    assert completed == []
