"""Monotonic deadline policy, independent of real time and threads for testing."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CycleTiming:
    requested_interval_ns: int
    observed_interval_ns: int | None
    lateness_ns: int
    missed_intervals: int


class NoCatchUpSchedule:
    """One cycle per wake, then a full interval after completion; never a backlog."""

    def __init__(self):
        self.disarm()

    def disarm(self) -> None:
        self.deadline_ns = None
        self._context = None
        self._last_start_ns = None

    def remaining(self, now_ns: int, period_ns: int | None, generation: int) -> int | None:
        if period_ns is None:
            self.disarm()
            return None
        if type(period_ns) is not int or period_ns < 1_000_000:
            raise ValueError("period must be an integer >= 1,000,000 ns")
        context = (period_ns, generation)
        if context != self._context:
            self._context = context
            self.deadline_ns = now_ns + period_ns
            self._last_start_ns = None
        return max(0, self.deadline_ns - now_ns)

    def complete(self, start_ns: int, end_ns: int) -> CycleTiming:
        if self.deadline_ns is None or start_ns < self.deadline_ns or end_ns < start_ns:
            raise ValueError("cycle must start at/after an armed deadline and finish later")
        period, _ = self._context
        late = start_ns - self.deadline_ns
        observed = None if self._last_start_ns is None else start_ns - self._last_start_ns
        self._last_start_ns = start_ns
        self.deadline_ns = end_ns + period
        return CycleTiming(period, observed, late, late // period)
