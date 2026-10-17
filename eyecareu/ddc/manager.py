"""High-level DDC/CI manager.

``MonitorManager`` discovers attached displays, selects a transport backend
(``ddcutil`` when available, otherwise the built-in ``i2c-dev`` backend),
resolves each monitor's MCCS capability string into the Eye-Care capability set
and offers typed accessors for the features the Windows build exposed
(brightness, volume, mute, colour/picture mode, pixel pivot, firmware, OSD).

All transport failures are contained: a monitor that does not answer DDC/CI is
still listed (its ``online`` flag is simply False) so the software eye-care
features keep working with software-only control.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

from .. import mccs
from ..models import CAPABILITY_MAP, MonitorCapabilities, KNOWN_MODELS
from .base import DdcBackend, MonitorIdentity, VcpValue
from .backlight import BacklightBackend
from .discovery import discover_monitors


@dataclass(slots=True)
class MonitorState:
    """Live state for one display."""

    identity: MonitorIdentity
    capabilities: MonitorCapabilities = field(default_factory=MonitorCapabilities)
    online: bool = False
    backend: str = ""
    capability_string: str = ""
    error: str = ""
    backlight: bool = False

    # cached readings
    brightness: VcpValue = field(default_factory=lambda: VcpValue(mccs.Vcp.BRIGHTNESS))
    volume: VcpValue = field(default_factory=lambda: VcpValue(mccs.Vcp.VOLUME))
    mute: VcpValue = field(default_factory=lambda: VcpValue(mccs.Vcp.MUTE))
    color_mode: VcpValue = field(default_factory=lambda: VcpValue(mccs.Vcp.COLOR_MODE))
    firmware: VcpValue = field(default_factory=lambda: VcpValue(mccs.Vcp.FIRMWARE))


def _parse_capability_string(text: str) -> set[str]:
    """Extract the MCCS capability names (e.g. ``Brightness``, ``Volume``)."""
    names: set[str] = set()
    for match in re.finditer(r"\b([A-Za-z][A-Za-z0-9\- ]{1,30}?)\s*\(", text):
        names.add(match.group(1).strip())
    # vcp(...) blocks also appear as "vcp(10 12 60 ...)" hex codes.
    return names


def _supported_vcps(text: str) -> set[int]:
    codes: set[int] = set()
    block = re.search(r"\bvcp\s*\(([^)]*)\)", text, re.IGNORECASE)
    if not block:
        return codes
    for token in re.split(r"[\s,]+", block.group(1)):
        token = token.strip()
        if re.fullmatch(r"[0-9A-Fa-f]{2}", token):
            codes.add(int(token, 16))
    return codes


class MonitorManager:
    """Owns discovery, backend selection and per-monitor state."""

    def __init__(self, backend: DdcBackend | None = None,
                 vcp_overrides: dict[str, int] | None = None,
                 prefer_benq: bool = True) -> None:
        self._lock = threading.RLock()
        self._monitors: dict[str, MonitorState] = {}
        self._vcp_overrides = dict(vcp_overrides or {})
        self._prefer_benq = prefer_benq
        self._backend = backend or self._default_backend()
        self._backlight = BacklightBackend()

    # -- backend selection -------------------------------------------------
    @staticmethod
    def _default_backend() -> DdcBackend:
        from .ddcutil import DdcutilBackend
        from .i2c import I2cDdcBackend
        if DdcutilBackend.available():
            return DdcutilBackend()
        return I2cDdcBackend()

    @property
    def backend_name(self) -> str:
        return self._backend.name

    def set_backend(self, backend: DdcBackend) -> None:
        with self._lock:
            try:
                self._backend.close()
            except Exception:
                pass
            self._backend = backend

    # -- vcp code resolution ----------------------------------------------
    def vcp(self, name: str, default: int) -> int:
        """Resolve an overridable VCP code (config overrides beat defaults)."""
        return int(self._vcp_overrides.get(name, default))

    # -- discovery ---------------------------------------------------------
    def refresh(self) -> list[MonitorState]:
        """Re-scan hardware and probe each monitor's capabilities."""
        discovered = discover_monitors()
        with self._lock:
            seen: set[str] = set()
            for identity in discovered:
                seen.add(identity.display_id)
                state = self._monitors.get(identity.display_id)
                if state is None:
                    state = MonitorState(identity=identity)
                    self._monitors[identity.display_id] = state
                else:
                    state.identity = identity
                self._probe(state)
            for display_id in list(self._monitors):
                if display_id not in seen:
                    del self._monitors[display_id]
            return list(self._monitors.values())

    def _probe(self, state: MonitorState) -> None:
        state.backend = self._backend.name
        state.backlight = self._backlight.supports(state.identity)
        # The VCP-version probe (0xDF) is the link test used by Monitor.dll.
        probe = self._backend.get_vcp(state.identity, mccs.Vcp.VCP_VERSION)
        state.online = probe.supported
        state.error = probe.error
        capabilities = self._backend.get_capabilities(state.identity)
        if not state.online and capabilities:
            state.online = True
            state.error = ""
        state.capability_string = capabilities
        state.capabilities = self._resolve_capabilities(state, capabilities)
        if state.backlight:
            # Internal panel: brightness comes from sysfs, independent of DDC.
            state.brightness = self._backlight.get_vcp(
                state.identity, mccs.Vcp.BRIGHTNESS)
        if state.online:
            self._refresh_values(state)

    def _resolve_capabilities(self, state: MonitorState,
                              capability_string: str) -> MonitorCapabilities:
        caps = MonitorCapabilities(model=state.identity.model)
        vcps = _supported_vcps(capability_string)
        names = _parse_capability_string(capability_string)

        if state.backlight:
            caps.capabilities.add("brightness")
            caps.capabilities.add("backlight")

        # Raw MCCS feature names -> Eye-Care capabilities.
        if mccs.Vcp.BRIGHTNESS in vcps or "Brightness" in names:
            caps.capabilities.add("brightness")
        if mccs.Vcp.VOLUME in vcps or "Volume" in names:
            caps.capabilities.add("volume")
        if "Mute" in names:
            caps.capabilities.add("mute")
        if "Select color preset" in names or mccs.Vcp.COLOR_MODE in vcps:
            caps.capabilities.add("color_mode")

        # The BenQ vendor features are declared by the panel itself.  When a
        # BenQ panel advertises these, expose the corresponding Eye-Care
        # capability; the vendor VCP code is resolved through overrides.
        bi_code = self.vcp("benq_bi", mccs.Vcp.BENQ_BI)
        lbl_code = self.vcp("benq_low_blue_light", mccs.Vcp.BENQ_LOW_BLUE_LIGHT)
        als_code = self.vcp("benq_low_light_sensor", mccs.Vcp.BENQ_LOW_LIGHT_SENSOR)
        for code, capability in ((bi_code, "brightness_intelligence"),
                                 (lbl_code, "low_blue_light"),
                                 (als_code, "ambient_light")):
            if code in vcps:
                caps.capabilities.add(capability)

        # BenQ panels always expose their software eye-care features even when
        # the model's MCCS string omits the vendor block.
        if state.identity.is_benq:
            caps.capabilities.update({"brightness", "low_blue_light"})
            caps.bi_type = "BI"

        caps.is_known_model = state.identity.model in KNOWN_MODELS
        caps.raw_features = {name: "on" for name in sorted(names)}
        return caps

    def _refresh_values(self, state: MonitorState) -> None:
        brightness_source = self._backlight if state.backlight else self._backend
        state.brightness = brightness_source.get_vcp(
            state.identity, self.vcp("brightness", mccs.Vcp.BRIGHTNESS))
        state.volume = self._backend.get_vcp(
            state.identity, self.vcp("volume", mccs.Vcp.VOLUME))
        state.mute = self._backend.get_vcp(
            state.identity, self.vcp("mute", mccs.Vcp.MUTE))
        state.color_mode = self._backend.get_vcp(
            state.identity, self.vcp("color_mode", mccs.Vcp.COLOR_MODE))
        state.firmware = self._backend.get_vcp(
            state.identity, self.vcp("firmware", mccs.Vcp.FIRMWARE))

    # -- access ------------------------------------------------------------
    def monitors(self) -> list[MonitorState]:
        with self._lock:
            return list(self._monitors.values())

    def monitor(self, display_id: str) -> MonitorState | None:
        with self._lock:
            return self._monitors.get(display_id)

    def get_vcp(self, display_id: str, name: str, default_code: int) -> VcpValue:
        with self._lock:
            state = self._monitors.get(display_id)
        if state is None:
            return VcpValue(vcp=default_code, error="unknown display")
        return self._backend.get_vcp(state.identity, self.vcp(name, default_code))

    def set_vcp(self, display_id: str, name: str, default_code: int, value: int) -> bool:
        with self._lock:
            state = self._monitors.get(display_id)
        if state is None:
            return False
        return self._backend.set_vcp(state.identity, self.vcp(name, default_code), value)

    # -- typed convenience -------------------------------------------------
    def set_brightness(self, display_id: str, percent: int) -> bool:
        percent = max(0, min(100, int(percent)))
        with self._lock:
            state = self._monitors.get(display_id)
        if state is None:
            return False
        maximum = state.brightness.maximum or 100
        value = round(percent * maximum / 100)
        if state.backlight:
            ok = self._backlight.set_vcp(state.identity, mccs.Vcp.BRIGHTNESS, value)
        else:
            ok = self._backend.set_vcp(
                state.identity, self.vcp("brightness", mccs.Vcp.BRIGHTNESS), value)
        if ok:
            state.brightness.current = value
            state.brightness.maximum = maximum
            state.brightness.supported = True
        return ok

    def set_volume(self, display_id: str, percent: int) -> bool:
        percent = max(0, min(100, int(percent)))
        with self._lock:
            state = self._monitors.get(display_id)
        if state is None:
            return False
        maximum = state.volume.maximum or 100
        value = round(percent * maximum / 100)
        ok = self._backend.set_vcp(
            state.identity, self.vcp("volume", mccs.Vcp.VOLUME), value)
        if ok:
            state.volume.current = value
            state.volume.maximum = maximum
            state.volume.supported = True
        return ok

    def set_mute(self, display_id: str, muted: bool) -> bool:
        # Monitor.dll wrote 1 for muted and 2 for unmuted.
        with self._lock:
            state = self._monitors.get(display_id)
        if state is None:
            return False
        ok = self._backend.set_vcp(
            state.identity, self.vcp("mute", mccs.Vcp.MUTE), 1 if muted else 2)
        if ok:
            state.mute.current = 1 if muted else 2
        return ok

    def set_color_mode(self, display_id: str, mode: int) -> bool:
        """Write a picture mode via 0xDC using the observed ``(hi<<8)|lo`` form."""
        with self._lock:
            state = self._monitors.get(display_id)
        if state is None:
            return False
        value = (0x00 << 8) | (int(mode) & 0xFF)
        ok = self._backend.set_vcp(
            state.identity, self.vcp("color_mode", mccs.Vcp.COLOR_MODE), value)
        if ok:
            state.color_mode.current = value
        return ok

    def close(self) -> None:
        with self._lock:
            try:
                self._backend.close()
            except Exception:
                pass
