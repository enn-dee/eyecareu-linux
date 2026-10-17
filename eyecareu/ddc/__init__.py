"""DDC/CI transport layer.

Exports the backend abstraction plus the two concrete backends and the
high-level :class:`~eyecareu.ddc.manager.MonitorManager`.
"""

from __future__ import annotations

from .base import DdcBackend, DdcError, MonitorIdentity, VcpValue
from .ddcutil import DdcutilBackend
from .discovery import discover_monitors, find_monitor
from .edid import manufacturer_name, parse_edid
from .i2c import I2cDdcBackend
from .manager import MonitorManager, MonitorState

__all__ = [
    "DdcBackend",
    "DdcError",
    "MonitorIdentity",
    "VcpValue",
    "DdcutilBackend",
    "I2cDdcBackend",
    "MonitorManager",
    "MonitorState",
    "discover_monitors",
    "find_monitor",
    "parse_edid",
    "manufacturer_name",
]
