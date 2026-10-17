"""Session and output discovery.

Eye-Care effects that touch the framebuffer (night light, low blue light,
software dimming) need a colour-management path.  On X11 that path is the
XRandR CRTC gamma ramp; on Wayland it depends on the compositor.  This module
classifies the running session and enumerates its outputs so the effect layer
can choose an implementation and the UI can explain what is available.
"""

from __future__ import annotations

import enum
import os
import re
import shutil
import subprocess
from dataclasses import dataclass


class SessionType(enum.Enum):
    X11 = "x11"
    WAYLAND = "wayland"
    HEADLESS = "headless"


@dataclass(slots=True)
class DisplayOutput:
    """One logical output as seen by the session."""

    name: str
    description: str = ""
    connected: bool = True
    primary: bool = False
    width_px: int = 0
    height_px: int = 0
    width_mm: int = 0
    height_mm: int = 0
    refresh_hz: float = 0.0
    crtc: int | None = None
    gamma_capable: bool = False
    connector: str = ""

    @property
    def dpi(self) -> float:
        if not self.width_px or not self.width_mm:
            return 0.0
        return self.width_px / (self.width_mm / 25.4)


def detect_session() -> SessionType:
    session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    if session == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        return SessionType.WAYLAND
    if session == "x11" or os.environ.get("DISPLAY"):
        if session == "x11":
            return SessionType.X11
        if os.environ.get("DISPLAY"):
            return SessionType.X11
    if session == "tty" or not (os.environ.get("DISPLAY")
                                or os.environ.get("WAYLAND_DISPLAY")):
        return SessionType.HEADLESS
    return SessionType.WAYLAND if session == "wayland" else SessionType.X11


def has_xrandr() -> bool:
    return shutil.which("xrandr") is not None


def _xrandr_query() -> str:
    try:
        proc = subprocess.run(["xrandr", "--query"], capture_output=True,
                              text=True, timeout=8, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout


_OUTPUT_RE = re.compile(
    r"^(?P<name>\S+)\s+(?P<status>connected|disconnected)"
    r"(?:\s+primary)?"
    r"(?:\s+(?P<w>\d+)x(?P<h>\d+)\+(?P<x>-?\d+)\+(?P<y>-?\d+))?"
)
_MODES_RE = re.compile(r"\s+(\d+)x(\d+)\s+(?P<rate>[\d.]+)\*?\+?")


def list_outputs_x11() -> list[DisplayOutput]:
    outputs: list[DisplayOutput] = []
    text = _xrandr_query()
    current: DisplayOutput | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        match = _OUTPUT_RE.match(line.strip())
        if match and not raw.startswith(" "):
            current = DisplayOutput(
                name=match.group("name"),
                connected=match.group("status") == "connected",
                primary="primary" in line,
                width_px=int(match.group("w") or 0),
                height_px=int(match.group("h") or 0),
                gamma_capable=True,
            )
            outputs.append(current)
            continue
        if current is not None:
            if "mm x" in line:
                mm = re.search(r"(\d+)mm x (\d+)mm", line)
                if mm:
                    current.width_mm = int(mm.group(1))
                    current.height_mm = int(mm.group(2))
                rate = re.search(r"[\d.]+\s*\*", line)
                if rate:
                    current.refresh_hz = float(rate.group(0).rstrip("*+ "))
            elif line.strip().startswith("CRTC"):
                crtc = re.search(r"CRTC\s+(\d+)", line)
                if crtc:
                    current.crtc = int(crtc.group(1))
    return outputs


def list_outputs_wayland() -> list[DisplayOutput]:
    """Best-effort Wayland enumeration (wlr-randr, then DRM connectors)."""
    outputs: list[DisplayOutput] = []
    if shutil.which("wlr-randr"):
        try:
            proc = subprocess.run(["wlr-randr"], capture_output=True, text=True,
                                  timeout=8, check=False)
            current: DisplayOutput | None = None
            for line in proc.stdout.splitlines():
                if line and not line[0].isspace():
                    current = DisplayOutput(name=line.split()[0])
                    outputs.append(current)
                elif current and line.strip().startswith("Enabled:"):
                    current.connected = "yes" in line
            if outputs:
                return outputs
        except (OSError, subprocess.TimeoutExpired):
            pass
    return outputs


def list_outputs() -> list[DisplayOutput]:
    session = detect_session()
    if session is SessionType.X11:
        return list_outputs_x11()
    if session is SessionType.WAYLAND:
        return list_outputs_wayland()
    return []
