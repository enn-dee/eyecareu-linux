"""``EyeCareCore`` - the QObject the QML user interface talks to.

It wires together every subsystem built in the other modules:

* :class:`~eyecareu.ddc.manager.MonitorManager`  hardware DDC/CI control
* :class:`~eyecareu.display.effects.DisplayEffects`  software colour effects
* :class:`~eyecareu.features.timers.PhaseTimer`  the 20-20-20 and Pomodoro timers
* :class:`~eyecareu.features.reminders.ReminderEngine`  break / low-light reminders
* :class:`~eyecareu.features.circadian.CircadianController`  scheduled warmth
* :class:`~eyecareu.features.report.ScreenTimeTracker`  the screen-time report

QML sees one flat object: configuration values as read/write properties,
live state as read-only properties and notification signals for anything that
changes on a timer.  All persistence is debounced so dragging a slider does not
write to disk on every pixel.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from . import autostart as autostart_mod
from .config import Config
from .ddc import MonitorManager
from .display import (
    DisplayEffects,
    SessionType,
    detect_session,
    overlay_rgba_string,
)
from .features.circadian import CircadianController
from .features.reminders import ReminderContext, ReminderEngine
from .features.report import ScreenTimeTracker
from .features.timers import PhaseTimer, make_pomodoro, make_twenty

#: Picture modes offered for VCP 0xDC (reverse engineered, see mccs.ColorMode).
_PICTURE_MODES: tuple[tuple[int, str], ...] = (
    (0x00, "Standard"),
    (0x01, "Care Mode"),
    (0x28, "Game"),
    (0x32, "Cinema"),
    (0x0F, "sRGB"),
    (0x1F, "User"),
    (0x1E, "M-Photo"),
    (0x03, "Dynamic"),
)


class EyeCareCore(QObject):
    """Application core exposed to QML."""

    # -- signals -----------------------------------------------------------
    monitorsChanged = Signal()
    selectedMonitorChanged = Signal()
    effectsChanged = Signal()
    effectsAvailabilityChanged = Signal()
    timerChanged = Signal(str)
    breakStarted = Signal(str)
    breakEnded = Signal(str)
    reminderTriggered = Signal(str, str, str)
    reportChanged = Signal()
    statusMessageChanged = Signal()
    configChanged = Signal()
    circadianChanged = Signal()

    def __init__(self, config: Config | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = config or Config.load()
        self._start = time.monotonic()

        self._manager = MonitorManager(
            vcp_overrides=self._cfg.ddc.vcp_overrides,
            prefer_benq=self._cfg.ddc.prefer_benq,
        )
        self._effects = DisplayEffects(self._cfg.effects)
        self._report = ScreenTimeTracker(
            retention_days=self._cfg.report.retention_days,
            daily_goal_minutes=self._cfg.report.daily_goal_minutes,
        )
        self._circadian = CircadianController(self._cfg.circadian)
        self._reminders = ReminderEngine()
        self._reminders.configure(self._cfg.reminders, self._now())

        self._twenty: PhaseTimer | None = None
        self._pomodoro: PhaseTimer | None = None
        self._twenty_state = None
        self._pomodoro_state = None

        self._selected = ""
        self._status = ""
        self._last_reminder: dict = {}
        self._overlay_visible = False
        self._overlay_kind = ""
        self._overlay_title = ""
        self._screen_overlay_visible = False
        self._screen_overlay_color = "#00000000"
        self._effects_mode = "gamma" if self._effects.available else "overlay"
        self._circadian_temp = int(self._cfg.circadian.day_temperature)
        self._circadian_phase = "day"
        self._idle_tool = shutil.which("xprintidle")

        # Debounced config persistence.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self._flush_config)

        # 1 Hz housekeeping loop.
        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(1000)
        self._ui_timer.timeout.connect(self._tick)
        self._ui_timer.start()

        # DDC polling loop.
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self.refreshMonitors)
        self._apply_poll_interval()

        self.refreshMonitors()
        self._apply_effects()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _now(self) -> float:
        return time.monotonic()

    def _set_status(self, message: str) -> None:
        self._status = message
        self.statusMessageChanged.emit()

    def _queue_save(self) -> None:
        self._save_timer.start()

    def _flush_config(self) -> None:
        try:
            self._cfg.save()
        except OSError as exc:
            self._set_status(f"could not save settings: {exc}")

    def _apply_poll_interval(self) -> None:
        interval = max(500, int(self._cfg.ddc.poll_interval_ms))
        self._poll_timer.setInterval(interval)
        self._poll_timer.start()

    # ------------------------------------------------------------------
    # session / backend (read-only)
    # ------------------------------------------------------------------
    @Property(str, constant=True)
    def sessionType(self) -> str:
        return detect_session().value

    @Property(str, notify=monitorsChanged)
    def backendName(self) -> str:
        return self._manager.backend_name

    @Property(bool, notify=effectsAvailabilityChanged)
    def effectsAvailable(self) -> bool:
        return self._effects.available

    @Property(str, notify=effectsAvailabilityChanged)
    def effectsError(self) -> str:
        return self._effects.error

    @Property(str, notify=statusMessageChanged)
    def statusMessage(self) -> str:
        return self._status

    # ------------------------------------------------------------------
    # monitors
    # ------------------------------------------------------------------
    @Property("QVariantList", notify=monitorsChanged)
    def monitors(self) -> list:
        out: list[dict] = []
        for state in self._manager.monitors():
            identity = state.identity
            out.append({
                "displayId": identity.display_id,
                "name": identity.label,
                "model": identity.model,
                "manufacturer": identity.manufacturer_name or identity.manufacturer,
                "connector": identity.connector,
                "isBenq": identity.is_benq,
                "online": state.online,
                "backend": state.backend,
                "brightness": state.brightness.percent if state.brightness.supported else 0,
                "brightnessSupported": "brightness" in state.capabilities.capabilities,
                "volume": state.volume.percent if state.volume.supported else 0,
                "volumeSupported": "volume" in state.capabilities.capabilities,
                "muted": state.mute.supported and state.mute.current == 1,
                "colorMode": (state.color_mode.current & 0xFF) if state.color_mode.supported else -1,
                "colorModeSupported": "color_mode" in state.capabilities.capabilities,
                "widthMm": identity.width_mm,
                "heightMm": identity.height_mm,
                "serial": identity.serial,
                "firmware": state.firmware.current if state.firmware.supported else 0,
                "capabilities": sorted(state.capabilities.capabilities),
                "error": state.error,
                "backlight": state.backlight,
            })
        return out

    @Property(str, notify=selectedMonitorChanged)
    def selectedDisplayId(self) -> str:
        return self._selected

    @selectedDisplayId.setter
    def selectedDisplayId(self, value: str) -> None:
        if value != self._selected:
            self._selected = value
            self.selectedMonitorChanged.emit()
            self.monitorsChanged.emit()

    @Property(str, notify=selectedMonitorChanged)
    def selectedMonitorName(self) -> str:
        for entry in self.monitors:
            if entry["displayId"] == self._selected:
                return entry["name"]
        return ""

    @Property("QVariantMap", notify=monitorsChanged)
    def selectedMonitor(self) -> dict:
        for entry in self.monitors:
            if entry["displayId"] == self._selected:
                return entry
        entries = self.monitors
        return entries[0] if entries else {}

    @Property("QVariantList", constant=True)
    def pictureModes(self) -> list:
        return [{"value": value, "label": label} for value, label in _PICTURE_MODES]

    @Slot()
    def refreshMonitors(self) -> None:
        states = self._manager.refresh()
        if states and not self._selected:
            self._selected = states[0].identity.display_id
            self.selectedMonitorChanged.emit()
        if self._selected and self._manager.monitor(self._selected) is None:
            self._selected = states[0].identity.display_id if states else ""
            self.selectedMonitorChanged.emit()
        self.monitorsChanged.emit()

    @Slot(str, int)
    def setBrightness(self, display_id: str, percent: int) -> None:
        if self._manager.set_brightness(display_id, percent):
            self.monitorsChanged.emit()
        else:
            self._set_status("the monitor did not accept the brightness change")

    @Slot(str, int)
    def setVolume(self, display_id: str, percent: int) -> None:
        if self._manager.set_volume(display_id, percent):
            self.monitorsChanged.emit()
        else:
            self._set_status("the monitor did not accept the volume change")

    @Slot(str, bool)
    def setMuted(self, display_id: str, muted: bool) -> None:
        if self._manager.set_mute(display_id, muted):
            self.monitorsChanged.emit()
        else:
            self._set_status("the monitor did not accept the mute change")

    @Slot(str, int)
    def setColorMode(self, display_id: str, mode: int) -> None:
        if self._manager.set_color_mode(display_id, mode):
            self.monitorsChanged.emit()
        else:
            self._set_status("the monitor did not accept the picture mode change")

    # ------------------------------------------------------------------
    # software effects
    # ------------------------------------------------------------------
    def _set_effect(self, field: str, value) -> None:
        setattr(self._cfg.effects, field, value)
        self._apply_effects()
        self._queue_save()
        self.effectsChanged.emit()

    def _effective_circadian_temperature(self) -> float | None:
        if not self._cfg.circadian.enabled:
            return None
        return self._circadian.state_at(datetime.now()).temperature

    def _apply_effects(self) -> None:
        self._effects.update_settings(self._cfg.effects,
                                      self._effective_circadian_temperature())
        if self._effects.available:
            # Real colour control: Hyprland CTM or X11 gamma ramps.
            self._effects_mode = self._effects.controller_name
            self._screen_overlay_visible = False
            self._screen_overlay_color = "#00000000"
            self._effects.apply()
        else:
            # Last resort: a translucent full-screen wash (unreliable on
            # compositors without layer-shell; real backends are preferred).
            self._effects_mode = "overlay"
            rgba = overlay_rgba_string(self._cfg.effects,
                                       self._effective_circadian_temperature())
            self._screen_overlay_color = rgba
            self._screen_overlay_visible = rgba != "#00000000"
        self.effectsAvailabilityChanged.emit()
        self.effectsChanged.emit()

    @Property(bool, notify=effectsChanged)
    def screenOverlayVisible(self) -> bool:
        return self._screen_overlay_visible

    @Property(str, notify=effectsChanged)
    def screenOverlayColor(self) -> str:
        return self._screen_overlay_color

    @Property(str, notify=effectsChanged)
    def effectsMode(self) -> str:
        return self._effects_mode

    nightLightEnabled = Property(bool,
        lambda self: self._cfg.effects.night_light_enabled,
        lambda self, v: self._set_effect("night_light_enabled", bool(v)),
        notify=effectsChanged)
    nightLightTemperature = Property(int,
        lambda self: self._cfg.effects.night_light_temperature,
        lambda self, v: self._set_effect("night_light_temperature", max(1000, min(10000, int(v)))),
        notify=effectsChanged)
    nightLightStrength = Property(int,
        lambda self: self._cfg.effects.night_light_strength,
        lambda self, v: self._set_effect("night_light_strength", max(0, min(100, int(v)))),
        notify=effectsChanged)
    lowBlueLightEnabled = Property(bool,
        lambda self: self._cfg.effects.low_blue_light_enabled,
        lambda self, v: self._set_effect("low_blue_light_enabled", bool(v)),
        notify=effectsChanged)
    lowBlueLightLevel = Property(int,
        lambda self: self._cfg.effects.low_blue_light_level,
        lambda self, v: self._set_effect("low_blue_light_level", max(0, min(100, int(v)))),
        notify=effectsChanged)
    softwareDimmingEnabled = Property(bool,
        lambda self: self._cfg.effects.software_dimming_enabled,
        lambda self, v: self._set_effect("software_dimming_enabled", bool(v)),
        notify=effectsChanged)
    softwareDimmingLevel = Property(int,
        lambda self: self._cfg.effects.software_dimming_level,
        lambda self, v: self._set_effect("software_dimming_level", max(5, min(100, int(v)))),
        notify=effectsChanged)
    warmTintEnabled = Property(bool,
        lambda self: self._cfg.effects.warm_tint_enabled,
        lambda self, v: self._set_effect("warm_tint_enabled", bool(v)),
        notify=effectsChanged)
    warmTintStrength = Property(int,
        lambda self: self._cfg.effects.warm_tint_strength,
        lambda self, v: self._set_effect("warm_tint_strength", max(0, min(100, int(v)))),
        notify=effectsChanged)
    clearTypeEnabled = Property(bool,
        lambda self: self._cfg.effects.cleartype_enabled,
        lambda self, v: self._set_effect("cleartype_enabled", bool(v)),
        notify=effectsChanged)

    @Slot()
    def resetEffects(self) -> None:
        self._cfg.effects.night_light_enabled = False
        self._cfg.effects.low_blue_light_enabled = False
        self._cfg.effects.software_dimming_enabled = False
        self._cfg.effects.warm_tint_enabled = False
        self._cfg.effects.cleartype_enabled = False
        self._set_effect("night_light_enabled", False)
        self._queue_save()
        self.effectsChanged.emit()

    # ------------------------------------------------------------------
    # circadian
    # ------------------------------------------------------------------
    def _set_circadian(self, field: str, value) -> None:
        setattr(self._cfg.circadian, field, value)
        self._circadian.update_settings(self._cfg.circadian)
        self._queue_save()
        self._update_circadian()
        self.circadianChanged.emit()

    circadianEnabled = Property(bool,
        lambda self: self._cfg.circadian.enabled,
        lambda self, v: self._set_circadian("enabled", bool(v)),
        notify=circadianChanged)
    circadianDayTemperature = Property(int,
        lambda self: self._cfg.circadian.day_temperature,
        lambda self, v: self._set_circadian("day_temperature", max(3000, min(10000, int(v)))),
        notify=circadianChanged)
    circadianNightTemperature = Property(int,
        lambda self: self._cfg.circadian.night_temperature,
        lambda self, v: self._set_circadian("night_temperature", max(2000, min(7000, int(v)))),
        notify=circadianChanged)
    circadianSunrise = Property(str,
        lambda self: self._cfg.circadian.sunrise,
        lambda self, v: self._set_circadian("sunrise", str(v)),
        notify=circadianChanged)
    circadianSunset = Property(str,
        lambda self: self._cfg.circadian.sunset,
        lambda self, v: self._set_circadian("sunset", str(v)),
        notify=circadianChanged)
    circadianTransitionMinutes = Property(int,
        lambda self: self._cfg.circadian.transition_minutes,
        lambda self, v: self._set_circadian("transition_minutes", max(1, min(240, int(v)))),
        notify=circadianChanged)
    circadianUseLocation = Property(bool,
        lambda self: self._cfg.circadian.use_location,
        lambda self, v: self._set_circadian("use_location", bool(v)),
        notify=circadianChanged)

    @Property(int, notify=circadianChanged)
    def circadianCurrentTemperature(self) -> int:
        return self._circadian_temp

    @Property(str, notify=circadianChanged)
    def circadianPhase(self) -> str:
        return self._circadian_phase

    def _update_circadian(self) -> None:
        if not self._cfg.circadian.enabled:
            return
        state = self._circadian.state_at(datetime.now())
        self._circadian_temp = int(state.temperature)
        self._circadian_phase = state.phase
        self._apply_effects()
        self.circadianChanged.emit()

    # ------------------------------------------------------------------
    # timers
    # ------------------------------------------------------------------
    def _on_timer_event(self, kind: str, name: str, state) -> None:
        if kind == "twenty":
            self._twenty_state = state
        else:
            self._pomodoro_state = state
        if name in ("break_start", "long_break_start"):
            self._overlay_visible = self._cfg.timers.show_break_overlay
            self._overlay_kind = kind
            self._overlay_title = ("Look 20 feet away" if kind == "twenty"
                                   else "Take a break")
            self.breakStarted.emit(kind)
        elif name == "break_end":
            if self._overlay_kind == kind:
                self._overlay_visible = False
            self.breakEnded.emit(kind)
        self.timerChanged.emit(kind)

    def _ensure_timers(self) -> None:
        if self._twenty is None:
            self._twenty = make_twenty(
                self._cfg.timers,
                on_event=lambda name, state: self._on_timer_event("twenty", name, state))
        if self._pomodoro is None:
            self._pomodoro = make_pomodoro(
                self._cfg.timers,
                on_event=lambda name, state: self._on_timer_event("pomodoro", name, state))

    def _rebuild_timers(self) -> None:
        was_twenty = self._twenty is not None and self._twenty.state(self._now()).running
        was_pomodoro = self._pomodoro is not None and self._pomodoro.state(self._now()).running
        self._ensure_timers()
        self._twenty = make_twenty(
            self._cfg.timers,
            on_event=lambda name, state: self._on_timer_event("twenty", name, state))
        self._pomodoro = make_pomodoro(
            self._cfg.timers,
            on_event=lambda name, state: self._on_timer_event("pomodoro", name, state))
        if was_twenty:
            self._twenty.start(self._now())
        if was_pomodoro:
            self._pomodoro.start(self._now())

    @Slot(bool)
    def setTwentyEnabled(self, enabled: bool) -> None:
        self._ensure_timers()
        if enabled:
            self._twenty.start(self._now())
        else:
            self._twenty.stop(self._now())
            self._overlay_visible = False
        self._cfg.timers.twenty_enabled = enabled
        self._queue_save()
        self.timerChanged.emit("twenty")

    @Slot(int)
    def setTwentyWorkMinutes(self, minutes: int) -> None:
        self._cfg.timers.twenty_work_minutes = max(1, min(120, int(minutes)))
        self._rebuild_timers()
        self._queue_save()
        self.timerChanged.emit("twenty")

    @Slot(int)
    def setTwentyBreakSeconds(self, seconds: int) -> None:
        self._cfg.timers.twenty_break_seconds = max(5, min(300, int(seconds)))
        self._rebuild_timers()
        self._queue_save()
        self.timerChanged.emit("twenty")

    @Slot()
    def toggleTwenty(self) -> None:
        self._ensure_timers()
        self._twenty.toggle(self._now())
        self.timerChanged.emit("twenty")

    @Slot()
    def stopTwenty(self) -> None:
        self._ensure_timers()
        self._twenty.stop(self._now())
        self._overlay_visible = False
        self.timerChanged.emit("twenty")

    @Slot()
    def skipTwenty(self) -> None:
        self._ensure_timers()
        self._twenty.skip(self._now())
        self.timerChanged.emit("twenty")

    @Slot(bool)
    def setPomodoroEnabled(self, enabled: bool) -> None:
        self._ensure_timers()
        if enabled:
            self._pomodoro.start(self._now())
        else:
            self._pomodoro.stop(self._now())
            self._overlay_visible = False
        self._cfg.timers.pomodoro_enabled = enabled
        self._queue_save()
        self.timerChanged.emit("pomodoro")

    @Slot(int)
    def setPomodoroWorkMinutes(self, minutes: int) -> None:
        self._cfg.timers.pomodoro_work_minutes = max(1, min(180, int(minutes)))
        self._rebuild_timers()
        self._queue_save()
        self.timerChanged.emit("pomodoro")

    @Slot(int)
    def setPomodoroShortBreakMinutes(self, minutes: int) -> None:
        self._cfg.timers.pomodoro_short_break_minutes = max(1, min(60, int(minutes)))
        self._rebuild_timers()
        self._queue_save()
        self.timerChanged.emit("pomodoro")

    @Slot(int)
    def setPomodoroLongBreakMinutes(self, minutes: int) -> None:
        self._cfg.timers.pomodoro_long_break_minutes = max(1, min(120, int(minutes)))
        self._rebuild_timers()
        self._queue_save()
        self.timerChanged.emit("pomodoro")

    @Slot(int)
    def setPomodoroCycles(self, cycles: int) -> None:
        self._cfg.timers.pomodoro_cycles_before_long = max(1, min(12, int(cycles)))
        self._rebuild_timers()
        self._queue_save()
        self.timerChanged.emit("pomodoro")

    @Slot(bool)
    def setPomodoroAutoStart(self, enabled: bool) -> None:
        self._cfg.timers.auto_start_next = bool(enabled)
        self._queue_save()
        self.timerChanged.emit("pomodoro")
        self.configChanged.emit()

    # Read/write views of the timer configuration (used by the QML sliders).
    twentyWorkMinutes = Property(int,
        lambda self: self._cfg.timers.twenty_work_minutes,
        lambda self, v: self.setTwentyWorkMinutes(int(v)),
        notify=timerChanged)
    twentyBreakSeconds = Property(int,
        lambda self: self._cfg.timers.twenty_break_seconds,
        lambda self, v: self.setTwentyBreakSeconds(int(v)),
        notify=timerChanged)
    pomodoroWorkMinutes = Property(int,
        lambda self: self._cfg.timers.pomodoro_work_minutes,
        lambda self, v: self.setPomodoroWorkMinutes(int(v)),
        notify=timerChanged)
    pomodoroShortBreakMinutes = Property(int,
        lambda self: self._cfg.timers.pomodoro_short_break_minutes,
        lambda self, v: self.setPomodoroShortBreakMinutes(int(v)),
        notify=timerChanged)
    pomodoroLongBreakMinutes = Property(int,
        lambda self: self._cfg.timers.pomodoro_long_break_minutes,
        lambda self, v: self.setPomodoroLongBreakMinutes(int(v)),
        notify=timerChanged)
    pomodoroCyclesBeforeLong = Property(int,
        lambda self: self._cfg.timers.pomodoro_cycles_before_long,
        lambda self, v: self.setPomodoroCycles(int(v)),
        notify=timerChanged)
    pomodoroAutoStart = Property(bool,
        lambda self: self._cfg.timers.auto_start_next,
        lambda self, v: self.setPomodoroAutoStart(bool(v)),
        notify=timerChanged)

    @Slot()
    def togglePomodoro(self) -> None:
        self._ensure_timers()
        self._pomodoro.toggle(self._now())
        self.timerChanged.emit("pomodoro")

    @Slot()
    def stopPomodoro(self) -> None:
        self._ensure_timers()
        self._pomodoro.stop(self._now())
        self._overlay_visible = False
        self.timerChanged.emit("pomodoro")

    @Slot()
    def skipPomodoro(self) -> None:
        self._ensure_timers()
        self._pomodoro.skip(self._now())
        self.timerChanged.emit("pomodoro")

    @Property(bool, notify=timerChanged)
    def twentyRunning(self) -> bool:
        self._ensure_timers()
        return self._twenty.state(self._now()).running

    @Property(bool, notify=timerChanged)
    def twentyPaused(self) -> bool:
        self._ensure_timers()
        return self._twenty.state(self._now()).paused

    @Property(str, notify=timerChanged)
    def twentyPhase(self) -> str:
        self._ensure_timers()
        return self._twenty.state(self._now()).phase

    @Property(int, notify=timerChanged)
    def twentyRemaining(self) -> int:
        self._ensure_timers()
        return int(self._twenty.remaining(self._now()))

    @Property(float, notify=timerChanged)
    def twentyProgress(self) -> float:
        self._ensure_timers()
        return self._twenty.state(self._now()).progress

    @Property(int, notify=timerChanged)
    def twentyCycles(self) -> int:
        self._ensure_timers()
        return self._twenty.state(self._now()).cycles

    @Property(bool, notify=timerChanged)
    def pomodoroRunning(self) -> bool:
        self._ensure_timers()
        return self._pomodoro.state(self._now()).running

    @Property(bool, notify=timerChanged)
    def pomodoroPaused(self) -> bool:
        self._ensure_timers()
        return self._pomodoro.state(self._now()).paused

    @Property(str, notify=timerChanged)
    def pomodoroPhase(self) -> str:
        self._ensure_timers()
        return self._pomodoro.state(self._now()).phase

    @Property(int, notify=timerChanged)
    def pomodoroRemaining(self) -> int:
        self._ensure_timers()
        return int(self._pomodoro.remaining(self._now()))

    @Property(float, notify=timerChanged)
    def pomodoroProgress(self) -> float:
        self._ensure_timers()
        return self._pomodoro.state(self._now()).progress

    @Property(int, notify=timerChanged)
    def pomodoroCycles(self) -> int:
        self._ensure_timers()
        return self._pomodoro.state(self._now()).cycles

    # ------------------------------------------------------------------
    # reminders
    # ------------------------------------------------------------------
    def _set_reminder(self, field: str, value, notify_extra=None) -> None:
        setattr(self._cfg.reminders, field, value)
        self._reminders.configure(self._cfg.reminders, self._now())
        self._queue_save()
        self.configChanged.emit()
        if notify_extra:
            notify_extra.emit()

    breakReminderEnabled = Property(bool,
        lambda self: self._cfg.reminders.break_reminder_enabled,
        lambda self, v: self._set_reminder("break_reminder_enabled", bool(v)),
        notify=configChanged)
    breakIntervalMinutes = Property(int,
        lambda self: self._cfg.reminders.break_interval_minutes,
        lambda self, v: self._set_reminder("break_interval_minutes", max(5, min(240, int(v)))),
        notify=configChanged)
    lowLightReminderEnabled = Property(bool,
        lambda self: self._cfg.reminders.low_light_reminder_enabled,
        lambda self, v: self._set_reminder("low_light_reminder_enabled", bool(v)),
        notify=configChanged)
    lowLightThreshold = Property(int,
        lambda self: self._cfg.reminders.low_light_threshold_lux,
        lambda self, v: self._set_reminder("low_light_threshold_lux", max(0, min(2000, int(v)))),
        notify=configChanged)
    distanceReminderEnabled = Property(bool,
        lambda self: self._cfg.reminders.distance_reminder_enabled,
        lambda self, v: self._set_reminder("distance_reminder_enabled", bool(v)),
        notify=configChanged)
    distanceCm = Property(int,
        lambda self: self._cfg.reminders.distance_cm,
        lambda self, v: self._set_reminder("distance_cm", max(30, min(120, int(v)))),
        notify=configChanged)
    postureReminderEnabled = Property(bool,
        lambda self: self._cfg.reminders.posture_reminder_enabled,
        lambda self, v: self._set_reminder("posture_reminder_enabled", bool(v)),
        notify=configChanged)

    @Slot(str)
    def snoozeReminder(self, kind: str) -> None:
        self._reminders.snooze(kind, self._now(), 10)
        self._overlay_visible = False
        self.reportChanged.emit()

    @Slot(str, str, str)
    def _emit_reminder(self, kind: str, title: str, message: str) -> None:
        self.reminderTriggered.emit(kind, title, message)

    # ------------------------------------------------------------------
    # report
    # ------------------------------------------------------------------
    @Property(bool,
        lambda self: self._cfg.report.enabled,
        lambda self, v: self._set_report("enabled", bool(v)),
        notify=configChanged)
    def reportEnabled(self) -> bool:
        return self._cfg.report.enabled

    dailyGoalMinutes = Property(int,
        lambda self: self._cfg.report.daily_goal_minutes,
        lambda self, v: self._set_report("daily_goal_minutes", max(30, min(1440, int(v)))),
        notify=configChanged)

    def _set_report(self, field: str, value) -> None:
        setattr(self._cfg.report, field, value)
        if field == "daily_goal_minutes":
            self._report.daily_goal_minutes = value
        self._queue_save()
        self.configChanged.emit()
        self.reportChanged.emit()

    @Property(int, notify=reportChanged)
    def todayMinutes(self) -> int:
        return self._report.today().total_minutes

    @Property(int, notify=reportChanged)
    def todayBreaks(self) -> int:
        return self._report.today().breaks

    @Property(int, notify=reportChanged)
    def todayStretchMinutes(self) -> int:
        return self._report.today().longest_stretch_minutes

    @Property(int, notify=reportChanged)
    def goalPercent(self) -> int:
        return self._report.stats()["goal_percent"]

    @Property(int, notify=reportChanged)
    def weekMinutes(self) -> int:
        return self._report.stats()["week_minutes"]

    @Property(int, notify=reportChanged)
    def weekAverageMinutes(self) -> int:
        return self._report.stats()["week_average_minutes"]

    @Property("QVariantList", notify=reportChanged)
    def weekData(self) -> list:
        return self._report.stats()["week"]

    @Slot()
    def clearReport(self) -> None:
        self._report.clear()
        self.reportChanged.emit()

    # ------------------------------------------------------------------
    # general
    # ------------------------------------------------------------------
    @Property(bool,
        lambda self: autostart_mod.is_enabled(),
        lambda self, v: self._set_autostart(bool(v)),
        notify=configChanged)
    def autostartEnabled(self) -> bool:
        return autostart_mod.is_enabled()

    def _set_autostart(self, enabled: bool) -> None:
        try:
            autostart_mod.set_enabled(enabled)
        except OSError as exc:
            self._set_status(f"could not change autostart: {exc}")
        self._cfg.general.autostart = enabled
        self._queue_save()
        self.configChanged.emit()

    @Property(bool,
        lambda self: self._cfg.general.close_to_tray,
        lambda self, v: self._set_general("close_to_tray", bool(v)),
        notify=configChanged)
    def closeToTray(self) -> bool:
        return self._cfg.general.close_to_tray

    @Property(bool,
        lambda self: self._cfg.general.start_minimised,
        lambda self, v: self._set_general("start_minimised", bool(v)),
        notify=configChanged)
    def startMinimised(self) -> bool:
        return self._cfg.general.start_minimised

    @Property(bool,
        lambda self: self._cfg.general.telemetry,
        lambda self, v: self._set_general("telemetry", bool(v)),
        notify=configChanged)
    def telemetry(self) -> bool:
        return self._cfg.general.telemetry

    def _set_general(self, field: str, value) -> None:
        setattr(self._cfg.general, field, value)
        self._queue_save()
        self.configChanged.emit()

    # ------------------------------------------------------------------
    # break overlay
    # ------------------------------------------------------------------
    @Property(bool, notify=timerChanged)
    def breakOverlayVisible(self) -> bool:
        return self._overlay_visible

    @Property(str, notify=timerChanged)
    def breakOverlayKind(self) -> str:
        return self._overlay_kind

    @Property(str, notify=timerChanged)
    def breakOverlayTitle(self) -> str:
        return self._overlay_title

    @Property(int, notify=timerChanged)
    def breakOverlayRemaining(self) -> int:
        self._ensure_timers()
        if self._overlay_kind == "twenty":
            return int(self._twenty.remaining(self._now()))
        if self._overlay_kind == "pomodoro":
            return int(self._pomodoro.remaining(self._now()))
        return 0

    @Slot()
    def dismissOverlay(self) -> None:
        self._overlay_visible = False
        self.timerChanged.emit("overlay")

    # ------------------------------------------------------------------
    # periodic tick
    # ------------------------------------------------------------------
    def _is_screen_active(self) -> bool:
        if not self._idle_tool:
            return True
        try:
            out = subprocess.run([self._idle_tool], capture_output=True, text=True,
                                 timeout=2, check=False).stdout.strip()
            return int(out) < 60_000  # idle < 60 s
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return True

    def _tick(self) -> None:
        now = self._now()
        any_running = False
        for timer in (self._twenty, self._pomodoro):
            if timer is None:
                continue
            timer.tick(now)
            if timer.state(now).running:
                any_running = True
        # Emit every second while a timer runs so the UI countdown updates.
        if any_running:
            self.timerChanged.emit("tick")

        active = self._is_screen_active()
        events = self._reminders.tick(ReminderContext(
            now=now, screen_active=active, ambient_lux=None))
        for event in events:
            self._last_reminder = {"kind": event.kind, "title": event.title,
                                   "message": event.message}
            self.reminderTriggered.emit(event.kind, event.title, event.message)

        if self._cfg.report.enabled:
            self._report.tick(now, active)
            if int(now) % 10 == 0:
                self._report.save()
                self.reportChanged.emit()

        if self._cfg.circadian.enabled and int(now) % 30 == 0:
            self._update_circadian()

    # ------------------------------------------------------------------
    # shutdown
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        self._ui_timer.stop()
        self._poll_timer.stop()
        try:
            self._report.save(force=True)
        except OSError:
            pass
        self._flush_config()
        self._effects.close()
        self._manager.close()
