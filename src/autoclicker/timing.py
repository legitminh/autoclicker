"""Calendar calculations and the one-shot scheduler; independent of the GUI."""

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from threading import Event, Lock, Thread
from time import time_ns
from zoneinfo import ZoneInfo


def nearest_minute(value: datetime) -> datetime:
    """Round on the timeline, with exactly 30 seconds rounding forward (also across DST)."""
    rounded = (value.astimezone(UTC) + timedelta(seconds=30)).replace(second=0, microsecond=0)
    return rounded.astimezone(value.tzinfo)


def local_candidates(
    anchor: date, days: int, hour: int, minute: int, second: int, millisecond: int, zone: ZoneInfo
) -> list[datetime]:
    """Return real instants for a local date/time; reject the spring-forward gap."""
    if not 0 <= days <= 9999:
        raise ValueError("Days must be between 0 and 9999.")
    if not 0 <= millisecond <= 999:
        raise ValueError("Milliseconds must be between 0 and 999.")
    try:
        wall = datetime.combine(
            anchor + timedelta(days=days), time(hour, minute, second, millisecond * 1000)
        )
    except (OverflowError, ValueError) as exc:
        raise ValueError("Enter a valid date and time.") from exc
    candidates = {}
    for fold in (0, 1):
        aware = wall.replace(tzinfo=zone, fold=fold)
        utc = aware.astimezone(UTC)
        if utc.astimezone(zone).replace(tzinfo=None) == wall:
            candidates[utc] = aware
    if not candidates:
        raise ValueError("This local time does not exist because the clocks move forward.")
    return [candidates[key] for key in sorted(candidates)]


def epoch_ns(value: datetime) -> int:
    delta = value.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


def relative_text(remaining_ns: int) -> str:
    milliseconds = abs(remaining_ns) // 1_000_000
    days, milliseconds = divmod(milliseconds, 86_400_000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    duration = f"{days}d {hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"
    return f"In {duration}" if remaining_ns > 0 else f"{duration} ago"


def wait_until(deadline_ns: int, cancelled: Event, clock: Callable[[], int] = time_ns) -> bool:
    """Recheck wall time so sleep/resume and clock corrections do not accumulate drift."""
    while not cancelled.is_set():
        remaining = deadline_ns - clock()
        if remaining <= 0:
            return True
        # Sleep interruptibly; tighten the interval near the requested millisecond.
        cancelled.wait(min(0.1, max(0.0001, remaining / 1_000_000_000 / 2)))
    return False


class ScheduledClick(Thread):
    """Execute at most once. Cancellation and click dispatch share a lock."""

    def __init__(
        self,
        deadline_ns: int,
        click: Callable[[], None],
        finished: Callable[[], None],
        failed: Callable[[str], None],
    ) -> None:
        super().__init__(name="scheduled-click", daemon=True)
        self.deadline_ns = deadline_ns
        self.click = click
        self.finished = finished
        self.failed = failed
        self.cancelled = Event()
        self._gate = Lock()

    def cancel(self) -> None:
        with self._gate:
            self.cancelled.set()

    def run(self) -> None:
        if not wait_until(self.deadline_ns, self.cancelled):
            return
        try:
            with self._gate:
                if self.cancelled.is_set():
                    return
                self.click()
        except Exception as exc:
            self.failed(str(exc))
        else:
            self.finished()
