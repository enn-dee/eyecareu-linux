"""Brightness control for internal panels through the sysfs backlight class.

Laptop panels (eDP/LVDS/DSI connectors) expose brightness at
``/sys/class/backlight/<device>/brightness`` (0..``max_brightness``).  That path
is separate from DDC/CI and is the only way to dim many internal displays, so it
is offered as a per-monitor backend for the brightness VCP code.

Writing requires permission on the ``brightness`` node; the shipped udev rule
grants it to the ``video`` group.  When it is not writable, reads still work and
writes fail cleanly, so the rest of the application is unaffected.
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import mccs
from .base import DdcBackend, MonitorIdentity, VcpValue

_BACKLIGHT_ROOT = Path("/sys/class/backlight")

_INTERNAL_CONNECTOR_PREFIXES = ("eDP", "LVDS", "DSI", "DPI")


def is_internal_connector(connector: str) -> bool:
    return connector.startswith(_INTERNAL_CONNECTOR_PREFIXES)


def available() -> bool:
    return _BACKLIGHT_ROOT.is_dir() and any(_BACKLIGHT_ROOT.iterdir())


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def find_device(connector: str) -> Path | None:
    """Return the backlight device for *connector*, or the first one."""
    if not _BACKLIGHT_ROOT.is_dir():
        return None
    candidates = sorted(_BACKLIGHT_ROOT.iterdir())
    # Prefer the device whose resolved path mentions the connector
    # (e.g. .../card1-eDP-1/amdgpu_bl1).
    for entry in candidates:
        try:
            target = os.path.realpath(entry)
        except OSError:
            target = str(entry)
        if connector and connector in target:
            return entry
    return candidates[0] if candidates else None


class BacklightBackend(DdcBackend):
    """Implements brightness (and only brightness) via sysfs backlight."""

    name = "backlight"

    def device_for(self, monitor: MonitorIdentity) -> Path | None:
        if not is_internal_connector(monitor.connector):
            return None
        return find_device(monitor.connector)

    def supports(self, monitor: MonitorIdentity) -> bool:
        return self.device_for(monitor) is not None

    def get_vcp(self, monitor: MonitorIdentity, vcp: int) -> VcpValue:
        device = self.device_for(monitor)
        if device is None:
            return VcpValue(vcp=vcp, error="no backlight device")
        if vcp != int(mccs.Vcp.BRIGHTNESS):
            return VcpValue(vcp=vcp, error="backlight supports brightness only")
        current = _read_int(device / "brightness")
        maximum = _read_int(device / "max_brightness")
        if current is None or not maximum:
            return VcpValue(vcp=vcp, error="cannot read backlight")
        return VcpValue(vcp=vcp, current=current, maximum=maximum,
                        vcp_type=0x00, supported=True)

    def set_vcp(self, monitor: MonitorIdentity, vcp: int, value: int) -> bool:
        device = self.device_for(monitor)
        if device is None or vcp != int(mccs.Vcp.BRIGHTNESS):
            return False
        maximum = _read_int(device / "max_brightness") or 100
        scaled = max(1, min(maximum, round(int(value) * maximum / max(1, maximum))))
        try:
            (device / "brightness").write_text(str(scaled), encoding="utf-8")
            return True
        except OSError:
            return False

    def get_capabilities(self, monitor: MonitorIdentity) -> str:
        return ""

    @staticmethod
    def available() -> bool:
        return available()
