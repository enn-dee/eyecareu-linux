"""Screen-time report.

Accumulates active screen time per calendar day and exposes the statistics the
Windows build surfaced in its *Eye-Care Report* / *Screen Time* pages: today's
total, the daily goal, the longest continuous stretch and the number of breaks
taken.

Only elapsed wall-clock time is stored (as plain numbers keyed by ISO date), so
the report is private and portable.  Writes are debounced to avoid hammering the
disk on every tick.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from pathlib import Path

from ..config import state_dir

#: A gap longer than this (seconds) is treated as a break / screen-off period.
_IDLE_GAP_SECONDS = 90.0
#: A continuous stretch at least this long (seconds) counts as one "break taken"
#: when it ends.
_BREAK_MIN_SECONDS = 300.0
_MAX_SANE_DELTA = 30.0


@dataclass
class DailyRecord:
    day: str = ""
    active_seconds: float = 0.0
    breaks: int = 0
    longest_stretch_seconds: float = 0.0
    sessions: int = 0

    @property
    def total_minutes(self) -> int:
        return int(self.active_seconds // 60)

    @property
    def longest_stretch_minutes(self) -> int:
        return int(self.longest_stretch_seconds // 60)


def _report_path() -> Path:
    return state_dir() / "screentime.json"


class ScreenTimeTracker:
    """Tracks active time and breaks, persisted to ``screentime.json``."""

    def __init__(self, path: Path | None = None, retention_days: int = 90,
                 daily_goal_minutes: int = 480) -> None:
        self._path = path or _report_path()
        self.retention_days = retention_days
        self.daily_goal_minutes = daily_goal_minutes
        self._records: dict[str, DailyRecord] = {}
        self._last_ts: float | None = None
        self._stretch = 0.0
        self._in_session = False
        self._dirty = False
        self.load()

    # -- persistence -------------------------------------------------------
    def load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        records = data.get("days", {}) if isinstance(data, dict) else {}
        for day, values in records.items():
            if not isinstance(values, dict):
                continue
            self._records[day] = DailyRecord(
                day=day,
                active_seconds=float(values.get("active_seconds", 0.0)),
                breaks=int(values.get("breaks", 0)),
                longest_stretch_seconds=float(values.get("longest_stretch_seconds", 0.0)),
                sessions=int(values.get("sessions", 0)),
            )

    def save(self, force: bool = False) -> None:
        if not self._dirty and not force:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"days": {day: asdict(record) for day, record in self._records.items()}}
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), prefix=".screentime-",
                                   suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)
            self._dirty = False
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    # -- accumulation ------------------------------------------------------
    def _today_key(self) -> str:
        return date.today().isoformat()

    def _record(self, day: str) -> DailyRecord:
        record = self._records.get(day)
        if record is None:
            record = DailyRecord(day=day)
            self._records[day] = record
        return record

    def tick(self, now: float, active: bool, now_wall: datetime | None = None) -> None:
        """Advance the tracker; ``now`` is a monotonic seconds clock."""
        wall = now_wall or datetime.now()
        day = wall.date().isoformat()
        record = self._record(day)
        if self._last_ts is None:
            self._last_ts = now
            return
        delta = now - self._last_ts
        self._last_ts = now
        if delta < 0 or delta > _MAX_SANE_DELTA:
            # Clock jump or a long suspend: treat as a break boundary.
            self._close_stretch(record)
            return
        if not active:
            self._close_stretch(record)
            return
        if not self._in_session:
            self._in_session = True
            record.sessions += 1
        record.active_seconds += delta
        self._stretch += delta
        record.longest_stretch_seconds = max(record.longest_stretch_seconds, self._stretch)
        self._dirty = True

    def _close_stretch(self, record: DailyRecord) -> None:
        if self._stretch >= _BREAK_MIN_SECONDS:
            record.breaks += 1
            self._dirty = True
        self._stretch = 0.0
        self._in_session = False

    def note_break(self) -> None:
        record = self._record(self._today_key())
        record.breaks += 1
        self._stretch = 0.0
        self._dirty = True

    def clear(self) -> None:
        """Erase all stored screen-time history."""
        self._records.clear()
        self._stretch = 0.0
        self._in_session = False
        self._last_ts = None
        self._dirty = True
        self.save(force=True)

    # -- queries -----------------------------------------------------------
    @property
    def current_stretch_seconds(self) -> float:
        return self._stretch

    def today(self) -> DailyRecord:
        return self._record(self._today_key())

    def day(self, day: str) -> DailyRecord:
        return self._record(day)

    def recent(self, days: int = 7) -> list[DailyRecord]:
        today = date.today()
        out: list[DailyRecord] = []
        for offset in range(days - 1, -1, -1):
            key = (today - timedelta(days=offset)).isoformat()
            out.append(self._records.get(key, DailyRecord(day=key)))
        return out

    def stats(self) -> dict:
        today = self.today()
        week = self.recent(7)
        week_total = sum(r.active_seconds for r in week)
        active_days = [r for r in week if r.active_seconds > 0]
        goal = max(1, self.daily_goal_minutes)
        return {
            "today_minutes": today.total_minutes,
            "today_stretch_minutes": today.longest_stretch_minutes,
            "today_breaks": today.breaks,
            "goal_minutes": self.daily_goal_minutes,
            "goal_percent": round(today.total_minutes * 100 / goal),
            "week_minutes": int(week_total // 60),
            "week_average_minutes": int((week_total / max(1, len(active_days))) // 60),
            "week": [{"day": r.day, "minutes": r.total_minutes,
                      "breaks": r.breaks, "stretch_minutes": r.longest_stretch_minutes}
                     for r in week],
        }

    def prune(self) -> None:
        cutoff = date.today() - timedelta(days=self.retention_days)
        for key in list(self._records):
            try:
                if date.fromisoformat(key) < cutoff:
                    del self._records[key]
                    self._dirty = True
            except ValueError:
                del self._records[key]
