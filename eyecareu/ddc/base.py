"""DDC/CI transport abstraction shared by the concrete backends."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass(slots=True)
class MonitorIdentity:
    """Identity of one physical display, from EDID + sysfs."""

    display_id: str                 # stable key, e.g. "card0-HDMI-A-1"
    connector: str = ""             # DRM connector name, e.g. "HDMI-A-1"
    i2c_bus: int | None = None       # i2c bus number used for DDC/CI
    manufacturer: str = ""          # 3-letter PNP id, e.g. "BNQ"
    manufacturer_name: str = ""     # resolved vendor name, e.g. "BenQ"
    model: str = ""                 # human model, e.g. "GW2490"
    product_code: int = 0
    serial: str = ""
    year: int = 0
    width_mm: int = 0
    height_mm: int = 0
    edid: bytes = b""

    @property
    def is_benq(self) -> bool:
        return self.manufacturer.upper() == "BNQ"

    @property
    def label(self) -> str:
        parts = [p for p in (self.manufacturer_name or self.manufacturer,
                             self.model or f"0x{self.product_code:04X}") if p]
        return " ".join(parts) or self.display_id


@dataclass(slots=True)
class VcpValue:
    """A single VCP reading."""

    vcp: int
    current: int = 0
    maximum: int = 0
    vcp_type: int = 0
    supported: bool = False
    error: str = ""

    @property
    def percent(self) -> int:
        if self.maximum <= 0:
            return 0
        return round(self.current * 100 / self.maximum)


class DdcError(RuntimeError):
    """Raised when a DDC/CI transaction fails at the transport level."""


class DdcBackend(abc.ABC):
    """Read/write MCCS VCP features on one display."""

    name: str = "base"

    @abc.abstractmethod
    def get_vcp(self, monitor: MonitorIdentity, vcp: int) -> VcpValue:
        """Return the current value of *vcp*."""

    @abc.abstractmethod
    def set_vcp(self, monitor: MonitorIdentity, vcp: int, value: int) -> bool:
        """Write *value* to *vcp*; return True on success."""

    def get_capabilities(self, monitor: MonitorIdentity) -> str:
        """Return the raw MCCS capability string, or "" when unavailable."""
        return ""

    def close(self) -> None:  # pragma: no cover - optional cleanup
        pass
