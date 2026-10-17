"""Focus / break timers: 20-20-20 and Pomodoro.

Both are the same phase machine with different durations, so they share
:class:`PhaseTimer`.  The machine is clock-injected (``now`` is a monotonic
number of seconds) which keeps it pure and unit-testable without sleeping.

Phases:

``idle``        not running
``work``        focused interval
``break``       short break (20 s for 20-20-20, 5 min for Pomodoro)
``long_break``  Pomodoro long break every N work cycles
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True)
class TimerState:
    kind: str
    phase: str
    remaining: float
    total: float
    cycles: int
    running: bool
    paused: bool
    message: str = ""

    @property
    def progress(self) -> float:
        if self.total <= 0:
            return 0.0
        return max(0.0, min(1.0, 1.0 - self.remaining / self.total))


_EVENT_NAMES = {
    ("idle", "work"): "work_start",
    ("work", "break"): "break_start",
    ("work", "long_break"): "long_break_start",
    ("break", "work"): "work_start",
    ("long_break", "work"): "work_start",
}


class PhaseTimer:
    """A repeating work/break interval timer."""

    def __init__(
        self,
        kind: str,
        work_seconds: float,
        break_seconds: float,
        long_break_seconds: float = 0.0,
        cycles_before_long: int = 0,
        auto_next: bool = True,
        on_event: Callable[[str, "TimerState"], None] | None = None,
    ) -> None:
        self.kind = kind
        self._work = float(work_seconds)
        self._break = float(break_seconds)
        self._long_break = float(long_break_seconds)
        self._cycles_before_long = int(cycles_before_long)
        self._auto_next = auto_next
        self._on_event = on_event

        self._phase = "idle"
        self._total = 0.0
        self._deadline = 0.0
        self._paused = False
        self._remaining_at_pause = 0.0
        self._cycles = 0

    # -- helpers -----------------------------------------------------------
    def _emit(self, name: str, now: float) -> None:
        if self._on_event:
            self._on_event(name, self.state(now))

    def _enter(self, phase: str, now: float) -> None:
        previous = self._phase
        self._phase = phase
        if phase == "work":
            self._total = self._work
            self._deadline = now + self._work
        elif phase == "long_break":
            self._total = self._long_break
            self._deadline = now + self._long_break
        elif phase == "break":
            self._total = self._break
            self._deadline = now + self._break
        else:
            self._total = 0.0
            self._deadline = now
        event = _EVENT_NAMES.get((previous, phase))
        if event:
            self._emit(event, now)

    def _is_long_break_due(self) -> bool:
        return (self._long_break > 0 and self._cycles_before_long > 0
                and self._cycles % self._cycles_before_long == 0)

    # -- API ---------------------------------------------------------------
    def start(self, now: float) -> TimerState:
        self._cycles = 0
        self._paused = False
        self._enter("work", now)
        return self.state(now)

    def stop(self, now: float) -> TimerState:
        if self._phase != "idle":
            self._emit("stopped", now)
        self._phase = "idle"
        self._paused = False
        self._total = 0.0
        return self.state(now)

    def pause(self, now: float) -> TimerState:
        if self._phase != "idle" and not self._paused:
            self._remaining_at_pause = max(0.0, self._deadline - now)
            self._paused = True
            self._emit("paused", now)
        return self.state(now)

    def resume(self, now: float) -> TimerState:
        if self._paused:
            self._deadline = now + self._remaining_at_pause
            self._paused = False
            self._emit("resumed", now)
        return self.state(now)

    def toggle(self, now: float) -> TimerState:
        if self._phase == "idle":
            return self.start(now)
        return self.pause(now) if not self._paused else self.resume(now)

    def skip(self, now: float) -> TimerState:
        """Advance to the next phase immediately."""
        if self._phase == "idle":
            return self.state(now)
        self._advance(now, skipped=True)
        return self.state(now)

    def reset(self, now: float) -> TimerState:
        self._cycles = 0
        self._paused = False
        self._enter("work", now)
        return self.state(now)

    def _advance(self, now: float, skipped: bool = False) -> None:
        if self._phase == "work":
            self._cycles += 1
            self._emit("work_end", now)
            if self._is_long_break_due():
                self._enter("long_break", now)
            else:
                self._enter("break", now)
        else:
            if self._phase in ("break", "long_break"):
                self._emit("break_end", now)
            if self._auto_next:
                self._enter("work", now)
            else:
                self._phase = "idle"
                self._total = 0.0

    def tick(self, now: float) -> TimerState | None:
        """Advance the clock; returns the state or None while nothing changed."""
        if self._phase == "idle" or self._paused:
            return None
        if now >= self._deadline:
            self._advance(now)
            return self.state(now)
        return None

    # -- state -------------------------------------------------------------
    def remaining(self, now: float) -> float:
        if self._phase == "idle":
            return 0.0
        if self._paused:
            return self._remaining_at_pause
        return max(0.0, self._deadline - now)

    def state(self, now: float) -> TimerState:
        return TimerState(
            kind=self.kind,
            phase=self._phase,
            remaining=self.remaining(now),
            total=self._total,
            cycles=self._cycles,
            running=self._phase != "idle",
            paused=self._paused,
        )


def make_twenty(timer_settings, on_event=None) -> PhaseTimer:
    """Build the 20-20-20 timer from configuration."""
    return PhaseTimer(
        kind="twenty",
        work_seconds=timer_settings.twenty_work_minutes * 60,
        break_seconds=timer_settings.twenty_break_seconds,
        auto_next=True,
        on_event=on_event,
    )


def make_pomodoro(timer_settings, on_event=None) -> PhaseTimer:
    """Build the Pomodoro timer from configuration."""
    return PhaseTimer(
        kind="pomodoro",
        work_seconds=timer_settings.pomodoro_work_minutes * 60,
        break_seconds=timer_settings.pomodoro_short_break_minutes * 60,
        long_break_seconds=timer_settings.pomodoro_long_break_minutes * 60,
        cycles_before_long=timer_settings.pomodoro_cycles_before_long,
        auto_next=timer_settings.auto_start_next,
        on_event=on_event,
    )
