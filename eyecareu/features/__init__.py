"""Eye-care features: timers, reminders, circadian mode and screen-time report."""

from __future__ import annotations

from .circadian import CircadianController, CircadianState, solar_times
from .reminders import (
    ConditionReminder,
    IntervalReminder,
    Reminder,
    ReminderContext,
    ReminderEngine,
    ReminderEvent,
)
from .report import DailyRecord, ScreenTimeTracker
from .timers import PhaseTimer, TimerState, make_pomodoro, make_twenty

__all__ = [
    "CircadianController",
    "CircadianState",
    "solar_times",
    "Reminder",
    "ReminderContext",
    "ReminderEngine",
    "ReminderEvent",
    "IntervalReminder",
    "ConditionReminder",
    "ScreenTimeTracker",
    "DailyRecord",
    "PhaseTimer",
    "TimerState",
    "make_twenty",
    "make_pomodoro",
]
