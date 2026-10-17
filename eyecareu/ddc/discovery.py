"""Detect attached displays and their DDC/CI i2c buses from sysfs.

Linux exposes each DRM connector under ``/sys/class/drm/card<N>-<CONNECTOR>``.
A connected connector provides an ``edid`` blob and a ``status`` file, and the
DDC/CI-capable physical link is reachable through the ``ddc`` symlink (present
on i915/amdgpu/nouveau for external outputs) or an ``i2c-<N>`` adapter whose
``name`` matches the connector.

The module deliberately degrades gracefully: on a headless build machine there
are simply no connectors, and the rest of the application still runs.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .base import MonitorIdentity
from .edid import parse_edid, manufacturer_name

_DRM_ROOT = Path("/sys/class/drm")
_I2C_DEV_ROOT = Path("/sys/class/i2c-dev")

# DRM connectors look like "card0-HDMI-A-1", "card1-DP-3", "card0-eDP-1".
_CONNECTOR_RE = re.compile(r"^card\d+-[A-Za-z]")


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        return b""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""


def _connector_entries() -> list[Path]:
    if not _DRM_ROOT.is_dir():
        return []
    return [entry for entry in sorted(_DRM_ROOT.iterdir())
            if _CONNECTOR_RE.match(entry.name)]


def _i2c_name_to_bus() -> dict[str, int]:
    """Map the i2c adapter ``name`` string to its bus number."""
    mapping: dict[str, int] = {}
    if not _I2C_DEV_ROOT.is_dir():
        return mapping
    for entry in sorted(_I2C_DEV_ROOT.iterdir()):
        if not entry.name.startswith("i2c-"):
            continue
        try:
            bus = int(entry.name.split("-", 1)[1])
        except ValueError:
            continue
        name = _read_text(entry / "name")
        if name:
            mapping[name] = bus
    return mapping


def _bus_from_ddc_symlink(connector: Path) -> int | None:
    link = connector / "ddc"
    try:
        resolved = os.readlink(link) if link.is_symlink() else ""
    except OSError:
        resolved = ""
    if resolved:
        base = os.path.basename(resolved.rstrip("/"))
        if base.startswith("i2c-"):
            try:
                return int(base.split("-", 1)[1])
            except ValueError:
                pass
    # Newer kernels expose a real directory with an "i2c-dev" child.
    child = connector / "ddc" / "i2c-dev"
    if child.is_dir():
        for entry in child.iterdir():
            if entry.name.startswith("i2c-"):
                try:
                    return int(entry.name.split("-", 1)[1])
                except ValueError:
                    pass
    return None


def _bus_for(connector_name: str, names: dict[str, int]) -> int | None:
    # The adapter name usually equals the connector name (e.g. "card0-HDMI-A-1").
    for candidate in (connector_name, connector_name.split("-", 1)[-1]):
        if candidate in names:
            return names[candidate]
    # Fall back to a substring match.
    for name, bus in names.items():
        if connector_name in name or name.endswith(connector_name):
            return bus
    return None


def discover_monitors() -> list[MonitorIdentity]:
    """Return every connected display with EDID + i2c bus resolved."""
    names = _i2c_name_to_bus()
    monitors: list[MonitorIdentity] = []
    for connector in _connector_entries():
        if _read_text(connector / "status") != "connected":
            continue
        edid = _read_bytes(connector / "edid")
        info = parse_edid(edid)
        bus = _bus_from_ddc_symlink(connector) or _bus_for(connector.name, names)
        identity = MonitorIdentity(
            display_id=connector.name,
            connector=connector.name.split("-", 1)[-1],
            i2c_bus=bus,
            manufacturer=info.get("manufacturer", ""),
            manufacturer_name=manufacturer_name(info.get("manufacturer", "")),
            model=info.get("model", ""),
            product_code=info.get("product_code", 0),
            serial=info.get("serial", ""),
            year=info.get("year", 0),
            width_mm=info.get("width_mm", 0),
            height_mm=info.get("height_mm", 0),
            edid=edid,
        )
        monitors.append(identity)
    return monitors


def find_monitor(display_id: str) -> MonitorIdentity | None:
    for monitor in discover_monitors():
        if monitor.display_id == display_id:
            return monitor
    return None
