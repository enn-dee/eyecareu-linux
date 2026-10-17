"""Autostart integration (XDG autostart + optional systemd user unit).

On Linux the portable way to start at login is an XDG autostart ``.desktop``
file in ``~/.config/autostart``.  We write one that runs ``eyecareu --tray`` and
honours the desktop's "start minimised" preference.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .version import APP_NAME


def _autostart_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(Path.home(), ".config")
    return Path(base) / "autostart"


def _autostart_file() -> Path:
    return _autostart_dir() / "eyecareu.desktop"


def _launch_command() -> str:
    # Prefer a console entry point when installed; otherwise run the module.
    executable = shutil.which("eyecareu")
    if executable:
        return f"{executable} --tray"
    return f"{sys.executable} -m eyecareu --tray"


def is_enabled() -> bool:
    return _autostart_file().exists()


def enable() -> None:
    target = _autostart_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        "Comment=Monitor eye-care assistant (DDC/CI + software effects)\n"
        f"Exec={_launch_command()}\n"
        "Icon=eyecareu\n"
        "Terminal=false\n"
        "Categories=Utility;Monitor;\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )


def disable() -> None:
    try:
        _autostart_file().unlink()
    except FileNotFoundError:
        pass


def set_enabled(enabled: bool) -> None:
    enable() if enabled else disable()
