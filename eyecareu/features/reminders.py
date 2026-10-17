"""Reminders: break, low-light, distance and posture.

Two kinds of trigger are supported:

* interval reminders (break, distance, posture) fire every N seconds while the
  screen is in use;
* condition reminders (low light) fire when a measured ambient-light value stays
  below a threshold.

The engine is clock-injected and pure; the core layer feeds it the current
monotonic time, screen-in-use state and (when a panel exposes it) the ambient
light reading, and surfaces the returned events to the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(slots=True)
class ReminderEvent:
    kind: str
    title: str
    message: str
    snoozed_until: float = 0.0


@dataclass(slots=True)
class ReminderContext:
    """Inputs evaluated by reminders on each tick."""

    now: float
    screen_active: bool = True
    ambient_lux: float | None = None


class Reminder:
    kind: str = "reminder"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self._snoozed_until = 0.0

    def snooze(self, now: float, minutes: int) -> None:
        self._snoozed_until = now + minutes * 60

    def reset(self, now: float) -> None:  # noqa: ARG002
        self._snoozed_until = 0.0

    def _blocked(self, now: float) -> bool:
        return now < self._snoozed_until

    def tick(self, context: ReminderContext) -> ReminderEvent | None:
        raise NotImplementedError


class IntervalReminder(Reminder):
    """Fires every ``interval_seconds`` of active screen time."""

    def __init__(self, kind: str, interval_seconds: float, title: str,
                 message: str, enabled: bool = False) -> None:
        super().__init__(enabled)
        self.kind = kind
        self.interval_seconds = float(interval_seconds)
        self.title = title
        self.message = message
        self._next_due = 0.0
        self._armed = False

    def arm(self, now: float) -> None:
        self._next_due = now + self.interval_seconds
        self._armed = True

    def reset(self, now: float) -> None:
        super().reset(now)
        self._armed = False

    def tick(self, context: ReminderContext) -> ReminderEvent | None:
        if not self.enabled:
            return None
        if not self._armed:
            self._next_due = context.now + self.interval_seconds
            self._armed = True
            return None
        if self._blocked(context.now):
            return None
        if not context.screen_active:
            return None
        if context.now >= self._next_due:
            self._next_due = context.now + self.interval_seconds
            return ReminderEvent(self.kind, self.title, self.message)
        return None


class ConditionReminder(Reminder):
    """Fires when a value stays below ``threshold`` for ``hold_seconds``."""

    def __init__(self, kind: str, threshold: float, hold_seconds: float,
                 title: str, message: str, enabled: bool = False) -> None:
        super().__init__(enabled)
        self.kind = kind
        self.threshold = float(threshold)
        self.hold_seconds = float(hold_seconds)
        self.title = title
        self.message = message
        self._low_since: float | None = None
        self._fired = False

    def reset(self, now: float) -> None:
        super().reset(now)
        self._low_since = None
        self._fired = False

    def tick(self, context: ReminderContext) -> ReminderEvent | None:
        if not self.enabled or context.ambient_lux is None:
            return None
        if context.ambient_lux >= self.threshold:
            self._low_since = None
            self._fired = False
            return None
        if self._low_since is None:
            self._low_since = context.now
            return None
        if self._fired or self._blocked(context.now):
            return None
        if context.now - self._low_since >= self.hold_seconds:
            self._fired = True
            return ReminderEvent(self.kind, self.title, self.message)
        return None


class ReminderEngine:
    """Holds the configured reminders and polls them on each tick."""

    def __init__(self) -> None:
        self.break_reminder: IntervalReminder | None = None
        self.distance_reminder: IntervalReminder | None = None
        self.posture_reminder: IntervalReminder | None = None
        self.low_light_reminder: ConditionReminder | None = None
        self._all: list[Reminder] = []

    def configure(self, settings, now: float) -> None:
        """(Re)build the reminder set from :class:`ReminderSettings`."""
        self.break_reminder = IntervalReminder(
            "break", settings.break_interval_minutes * 60,
            "Time for a break", "Look away from the screen for a minute.",
            enabled=settings.break_reminder_enabled)
        self.distance_reminder = IntervalReminder(
            "distance", 30 * 60,
            "Check your distance",
            f"Keep about {settings.distance_cm} cm between you and the screen.",
            enabled=settings.distance_reminder_enabled)
        self.posture_reminder = IntervalReminder(
            "posture", 45 * 60,
            "Check your posture", "Sit upright and relax your shoulders.",
            enabled=settings.posture_reminder_enabled)
        self.low_light_reminder = ConditionReminder(
            "low_light", settings.low_light_threshold_lux, 30.0,
            "It is getting dark",
            "Ambient light is low - brighten the room or the screen.",
            enabled=settings.low_light_reminder_enabled)
        self._all = [r for r in (self.break_reminder, self.distance_reminder,
                                 self.posture_reminder, self.low_light_reminder)
                     if r is not None]

    def tick(self, context: ReminderContext) -> list[ReminderEvent]:
        events: list[ReminderEvent] = []
        for reminder in self._all:
            event = reminder.tick(context)
            if event is not None:
                events.append(event)
        return events

    def snooze(self, kind: str, now: float, minutes: int = 10) -> bool:
        for reminder in self._all:
            if reminder.kind == kind:
                reminder.snooze(now, minutes)
                return True
        return False

    def reset_all(self, now: float) -> None:
        for reminder in self._all:
            reminder.reset(now)
