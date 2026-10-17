"""Persistent user configuration.

Settings are stored as JSON under the XDG config directory
(``~/.config/eyecareu/config.json``) using atomic replace so a crash mid-write
never leaves a truncated file.  Unknown keys are preserved on load so a newer
build can add fields without an older one discarding them.

The schema mirrors the option surface recovered from the Windows build
(Eye-CareU v1.5.5.0): brightness/volume/colour control, the 20-20-20 and
Pomodoro timers, break/low-light reminders, circadian colour temperature,
software eye-care effects and the screen-time report.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    return Path(base) / "eyecareu"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(Path.home(), ".local", "state")
    return Path(base) / "eyecareu"


def config_path() -> Path:
    return config_dir() / "config.json"


# --------------------------------------------------------------------------
# Section dataclasses
# --------------------------------------------------------------------------
@dataclass
class GeneralSettings:
    language: str = "en"
    start_minimised: bool = False
    close_to_tray: bool = True
    autostart: bool = False
    telemetry: bool = False          # the Windows build used GA/Matomo; off by default here
    theme: str = "system"            # "system" | "light" | "dark"


@dataclass
class DdcSettings:
    backend: str = "auto"            # "auto" | "ddcutil" | "i2c"
    poll_interval_ms: int = 2000
    prefer_benq: bool = True
    # VCP overrides for panels whose vendor codes differ from the defaults.
    vcp_overrides: dict[str, int] = field(default_factory=dict)


@dataclass
class TimerSettings:
    twenty_enabled: bool = False
    twenty_work_minutes: int = 20
    twenty_break_seconds: int = 20
    pomodoro_enabled: bool = False
    pomodoro_work_minutes: int = 25
    pomodoro_short_break_minutes: int = 5
    pomodoro_long_break_minutes: int = 15
    pomodoro_cycles_before_long: int = 4
    auto_start_next: bool = True
    show_break_overlay: bool = True


@dataclass
class ReminderSettings:
    break_reminder_enabled: bool = False
    break_interval_minutes: int = 60
    low_light_reminder_enabled: bool = False
    low_light_threshold_lux: int = 100
    distance_reminder_enabled: bool = False     # present until v1.3.3.0, kept as opt-in
    distance_cm: int = 60
    posture_reminder_enabled: bool = False


@dataclass
class CircadianSettings:
    enabled: bool = False
    day_temperature: int = 6500
    night_temperature: int = 3400
    sunrise: str = "07:00"
    sunset: str = "19:00"
    transition_minutes: int = 60
    latitude: float | None = None
    longitude: float | None = None
    use_location: bool = False


@dataclass
class EffectSettings:
    night_light_enabled: bool = False
    night_light_temperature: int = 4500
    night_light_strength: int = 50            # 0-100
    low_blue_light_enabled: bool = False
    low_blue_light_level: int = 50            # 0-100
    software_dimming_enabled: bool = False
    software_dimming_level: int = 100         # 100 = no dimming, 10 = dark
    warm_tint_enabled: bool = False
    warm_tint_strength: int = 30
    cleartype_enabled: bool = False           # text contrast / gamma tweak
    effect_on_all_monitors: bool = True


@dataclass
class ReportSettings:
    enabled: bool = True
    retention_days: int = 90
    daily_goal_minutes: int = 480
    warn_continuous_minutes: int = 120


@dataclass
class Config:
    version: int = 1
    general: GeneralSettings = field(default_factory=GeneralSettings)
    ddc: DdcSettings = field(default_factory=DdcSettings)
    timers: TimerSettings = field(default_factory=TimerSettings)
    reminders: ReminderSettings = field(default_factory=ReminderSettings)
    circadian: CircadianSettings = field(default_factory=CircadianSettings)
    effects: EffectSettings = field(default_factory=EffectSettings)
    report: ReportSettings = field(default_factory=ReportSettings)

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        cfg = cls()
        for section in ("general", "ddc", "timers", "reminders",
                        "circadian", "effects", "report"):
            values = data.get(section)
            if not isinstance(values, dict):
                continue
            target = getattr(cfg, section)
            known = {f for f in target.__dataclass_fields__}  # type: ignore[attr-defined]
            for key, value in values.items():
                if key in known:
                    setattr(target, key, value)
        if isinstance(data.get("version"), int):
            cfg.version = data["version"]
        return cfg

    # -- persistence -------------------------------------------------------
    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        target = path or config_path()
        try:
            raw = target.read_text(encoding="utf-8")
        except OSError:
            return cls()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls.from_dict(data)

    def save(self, path: Path | None = None) -> None:
        target = path or config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), indent=2, sort_keys=True)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".config-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
