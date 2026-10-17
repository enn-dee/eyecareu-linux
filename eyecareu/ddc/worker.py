"""Serialised DDC/CI worker running on its own thread.

A single DDC/CI round trip costs tens of milliseconds (the VESA spec mandates a
~40 ms settle time) and a full monitor probe — link test + capability string +
value reads — costs seconds.  The Windows build does not perform that traffic on
its UI thread: ``EcShared.dll`` carries the comment *"Since property writes
involving VCP are performed on a separate thread"* next to ``QThread``,
``QMutex`` and ``QTimer`` usage.  This module mirrors that split.

:class:`DdcWorker` owns the :class:`~eyecareu.ddc.manager.MonitorManager` on a
background ``QThread``; every DDC operation runs there.  The GUI thread only
reads the manager's cached state (guarded by a lock) and reacts to the
``changed`` signal, so it never blocks on the i2c bus.

Writes are coalesced: dragging a slider emits a request per pixel, but only the
latest value for each control is actually sent to the panel, so the bus never
accumulates a backlog when the display is slow to answer.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from .. import mccs
from .manager import MonitorManager

#: The DDC poll interval is never allowed below this.
_MIN_INTERVAL_MS = 500


class DdcWorker(QObject):
    """Runs every DDC/CI operation on the thread this object lives in."""

    #: Emitted after any operation that may have changed cached state.
    changed = Signal()
    #: Emitted with a human-readable message when an operation is refused.
    failed = Signal(str)

    def __init__(self, manager: MonitorManager) -> None:
        super().__init__()
        self._manager = manager
        self._interval_ms = 2000
        self._timer: QTimer | None = None
        self._flush_timer: QTimer | None = None
        # key -> (operation, failure message, args); newest request wins.
        self._pending: dict[str, tuple] = {}

    # -- lifecycle (all slots run in the worker thread) --------------------
    @Slot()
    def start(self) -> None:
        """Create the timers and take the first full reading."""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._poll)

        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(0)
        self._flush_timer.timeout.connect(self._flush)

        self._refresh(False)

    @Slot(int)
    def set_interval(self, milliseconds: int) -> None:
        self._interval_ms = max(_MIN_INTERVAL_MS, int(milliseconds))

    @Slot(bool)
    def refresh(self, reload_capabilities: bool = False) -> None:
        """Re-scan displays; *reload_capabilities* forces a capability re-read."""
        self._refresh(reload_capabilities)

    @Slot()
    def shutdown(self) -> None:
        for timer in (self._timer, self._flush_timer):
            if timer is not None:
                timer.stop()
        self._timer = None
        self._flush_timer = None
        self._pending.clear()
        # Anything already queued must still reach the panel before we go.
        self._manager.close()

    # -- periodic polling --------------------------------------------------
    def _schedule(self) -> None:
        # Single-shot and re-armed *after* each cycle so slow bus traffic can
        # never queue up a backlog of overlapping polls.
        if self._timer is not None:
            self._timer.start(self._interval_ms)

    @Slot()
    def _poll(self) -> None:
        try:
            self._manager.poll()
        except Exception as exc:                      # keep the loop alive
            self.failed.emit(f"display polling failed: {exc}")
        finally:
            self.changed.emit()
            self._schedule()

    def _refresh(self, reload_capabilities: bool) -> None:
        try:
            # Publish the monitor list as soon as sysfs has been read so the UI
            # shows the displays immediately, then fill in the slow readings.
            self._manager.discover()
            self.changed.emit()
            self._manager.refresh(reload_capabilities=reload_capabilities,
                                  on_update=self.changed.emit)
        except Exception as exc:
            self.failed.emit(f"display scan failed: {exc}")
        finally:
            self.changed.emit()
            self._schedule()

    # -- operations --------------------------------------------------------
    @Slot(str, int)
    def set_brightness(self, display_id: str, percent: int) -> None:
        self._enqueue(f"{display_id}:brightness", self._manager.set_brightness,
                      "the monitor did not accept the brightness change",
                      (display_id, int(percent)))

    @Slot(str, int)
    def set_volume(self, display_id: str, percent: int) -> None:
        self._enqueue(f"{display_id}:volume", self._manager.set_volume,
                      "the monitor did not accept the volume change",
                      (display_id, int(percent)))

    @Slot(str, bool)
    def set_mute(self, display_id: str, muted: bool) -> None:
        self._enqueue(f"{display_id}:mute", self._manager.set_mute,
                      "the monitor did not accept the mute change",
                      (display_id, bool(muted)))

    @Slot(str, int)
    def set_color_mode(self, display_id: str, mode: int) -> None:
        self._enqueue(f"{display_id}:color_mode", self._manager.set_color_mode,
                      f"the monitor did not accept the '{mccs.color_mode_name(mode)}' "
                      "picture mode over DDC/CI - some modes are OSD-only on this model",
                      (display_id, int(mode)))

    def _enqueue(self, key: str, operation, failure_message: str, args: tuple) -> None:
        self._pending[key] = (operation, failure_message, args)
        if self._flush_timer is not None:
            self._flush_timer.start()

    @Slot()
    def _flush(self) -> None:
        pending, self._pending = self._pending, {}
        for operation, failure_message, args in pending.values():
            try:
                ok = operation(*args)
            except Exception as exc:
                self.failed.emit(str(exc))
            else:
                if not ok:
                    self.failed.emit(failure_message)
        if pending:
            self.changed.emit()
