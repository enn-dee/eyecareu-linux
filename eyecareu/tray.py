"""System tray integration.

The tray mirrors the Windows build's notification-area icon: it shows the
current monitor, toggles night light and the 20-20-20 timer, and offers
show/hide and quit.  The icon is painted at runtime so the package needs no
image assets.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


def make_icon(size: int = 64) -> QIcon:
    """Draw a simple eye-care icon (an eye over a warm gradient circle)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#2f6f4f"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, size - 4, size - 4)

    # Eye outline (white almond) and iris.
    painter.setBrush(QColor("#ffffff"))
    cx, cy = size / 2, size / 2
    painter.drawEllipse(cx - size * 0.30, cy - size * 0.16,
                        size * 0.60, size * 0.32)
    painter.setBrush(QColor("#1d1d1f"))
    painter.drawEllipse(cx - size * 0.11, cy - size * 0.11,
                        size * 0.22, size * 0.22)
    painter.end()
    return QIcon(pixmap)


class EyeCareTray(QObject):
    """Owns the QSystemTrayIcon and its menu."""

    def __init__(self, core, app, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._core = core
        self._app = app
        self._window = None

        self.icon = QSystemTrayIcon(make_icon(), self)
        self.icon.setToolTip("Eye-CareU")
        menu = QMenu()

        self.show_action = QAction("Show Eye-CareU", menu)
        self.show_action.triggered.connect(self.show_window)
        menu.addAction(self.show_action)

        menu.addSeparator()

        self.night_action = QAction("Night light", menu)
        self.night_action.setCheckable(True)
        self.night_action.setChecked(core.nightLightEnabled)
        self.night_action.toggled.connect(
            lambda v: core.setProperty("nightLightEnabled", v))
        menu.addAction(self.night_action)

        self.blue_action = QAction("Low blue light", menu)
        self.blue_action.setCheckable(True)
        self.blue_action.setChecked(core.lowBlueLightEnabled)
        self.blue_action.toggled.connect(
            lambda v: core.setProperty("lowBlueLightEnabled", v))
        menu.addAction(self.blue_action)

        self.twenty_action = QAction("20-20-20 timer", menu)
        self.twenty_action.setCheckable(True)
        self.twenty_action.setChecked(core.twentyRunning)
        self.twenty_action.toggled.connect(core.setTwentyEnabled)
        menu.addAction(self.twenty_action)

        self.pomodoro_action = QAction("Pomodoro timer", menu)
        self.pomodoro_action.setCheckable(True)
        self.pomodoro_action.setChecked(core.pomodoroRunning)
        self.pomodoro_action.toggled.connect(core.setPomodoroEnabled)
        menu.addAction(self.pomodoro_action)

        menu.addSeparator()

        self.quit_action = QAction("Quit", menu)
        self.quit_action.triggered.connect(self._quit)
        menu.addAction(self.quit_action)

        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._on_activated)

        core.effectsChanged.connect(self._sync_checks)
        core.timerChanged.connect(self._on_timer_changed)

    # -- window binding ----------------------------------------------------
    def bind_window(self, window) -> None:
        self._window = window

    def show(self) -> None:
        self.icon.show()

    def show_window(self) -> None:
        if self._window is None:
            return
        self._window.show()
        self._window.raise_()
        self._window.requestActivate()

    # -- slots -------------------------------------------------------------
    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def _sync_checks(self) -> None:
        self.night_action.setChecked(self._core.nightLightEnabled)
        self.blue_action.setChecked(self._core.lowBlueLightEnabled)

    def _on_timer_changed(self, kind: str) -> None:
        if kind in ("twenty", "tick"):
            self.twenty_action.setChecked(self._core.twentyRunning)
        if kind in ("pomodoro", "tick"):
            self.pomodoro_action.setChecked(self._core.pomodoroRunning)

    def _quit(self) -> None:
        self._core.shutdown()
        self._app.quit()

    def notify(self, title: str, message: str) -> None:
        if QSystemTrayIcon.supportsMessages():
            self.icon.showMessage(title, message, make_icon(), 8000)
