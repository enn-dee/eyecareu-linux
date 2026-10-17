"""Application bootstrap: build the Qt app, the core and the QML engine."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from .config import Config
from .core import EyeCareCore
from .tray import EyeCareTray
from .version import APP_ID, APP_NAME, ORG_NAME, WINDOWS_SOURCE_VERSION, __version__


def qml_dir() -> Path:
    """Locate the bundled QML directory (package-local, dev fallback)."""
    packaged = Path(__file__).resolve().parent / "qml"
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parent.parent / "qml"


def build_application(argv: list[str] | None = None,
                      minimised: bool = False) -> tuple[QApplication, EyeCareCore,
                                                         QQmlApplicationEngine,
                                                         EyeCareTray]:
    """Create the application, core, QML engine and tray (not yet shown)."""
    QQuickStyle.setStyle("Basic")
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)   # the tray keeps the app alive

    config = Config.load()
    core = EyeCareCore(config)
    tray = EyeCareTray(core, app)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("core", core)
    engine.rootContext().setContextProperty("appVersion", __version__)
    engine.rootContext().setContextProperty("appName", APP_NAME)
    engine.rootContext().setContextProperty("sourceVersion", WINDOWS_SOURCE_VERSION)

    engine.load(QUrl.fromLocalFile(str(qml_dir() / "main.qml")))

    if engine.rootObjects():
        window = engine.rootObjects()[0]
        tray.bind_window(window)
        if not minimised and not config.general.start_minimised:
            window.show()
        else:
            window.hide()
    else:
        print("warning: QML failed to load", file=sys.stderr)

    tray.show()
    app.aboutToQuit.connect(core.shutdown)
    return app, core, engine, tray


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    # If the user was just added to the i2c/video groups, activate them now so
    # hardware access works without requiring a logout.  Never returns if it
    # performs the switch.
    from .regroup import maybe_reexec
    maybe_reexec([sys.argv[0], *args])
    if "--doctor" in args:
        from .doctor import run as run_doctor
        return run_doctor()
    tray_only = "--tray" in args
    minimised = tray_only or "--minimised" in args
    # Qt consumes its own flags from sys.argv; hand it a cleaned list.
    app, _core, _engine, _tray = build_application([sys.argv[0]], minimised=minimised)
    exit_after = os.environ.get("EYECAREU_EXIT_AFTER_MS")
    if exit_after:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(int(exit_after), app.quit)
    try:
        return app.exec()
    finally:
        # Destroy the QML engine before the Python-owned core so live bindings
        # never touch a dangling object during shutdown.
        del _engine
        del _tray
        del _core

