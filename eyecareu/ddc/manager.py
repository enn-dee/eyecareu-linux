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
import time
from dataclasses import dataclass, field

from .. import mccs
from ..models import CAPABILITY_MAP, MonitorCapabilities, KNOWN_MODELS
from . import capcache
from .base import DdcBackend, MonitorIdentity, VcpValue
from .backlight import BacklightBackend
from .discovery import discover_monitors

#: How long to wait before re-probing a display that failed its link test.
OFFLINE_RETRY_SECONDS = 8.0
#: How many times to retry the (flaky) capability read before using defaults.
CAPABILITY_ATTEMPTS = 3
#: Sentinel for "this display is fully probed and needs no further retry".
NO_RETRY = float("inf")


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
    color_modes: list[int] = field(default_factory=list)
    #: True once a full probe (link test + capability read) has run, so the UI
    #: can avoid offering a guessed picture-mode list while still scanning.
    probed: bool = False
    #: Monotonic time before which this display is not re-probed.
    retry_after: float = 0.0
    #: Number of consecutive failed capability reads.
    caps_attempts: int = 0

    # cached readings
    brightness: VcpValue = field(default_factory=lambda: VcpValue(mccs.Vcp.BRIGHTNESS))
    volume: VcpValue = field(default_factory=lambda: VcpValue(mccs.Vcp.VOLUME))
    mute: VcpValue = field(default_factory=lambda: VcpValue(mccs.Vcp.MUTE))
    color_mode: VcpValue = field(default_factory=lambda: VcpValue(mccs.Vcp.COLOR_MODE))
    firmware: VcpValue = field(default_factory=lambda: VcpValue(mccs.Vcp.FIRMWARE))


def _capability_vcp_block(text: str) -> str:
    """Return the contents of the ``vcp( ... )`` block, parens balanced.

    A naive ``\\(([^)]*)\\)`` stops at the *first* ``)``, which for real BenQ
    panels is inside a nested value list (``vcp(... 14(04 05 08 0B) 16 ...)``)
    and truncates the block before codes such as ``62`` (volume) and ``DC``
    (picture mode).  This walks the nesting instead.
    """
    match = re.search(r"\bvcp\s*\(", text, re.IGNORECASE)
    if not match:
        return ""
    depth = 1
    index = match.end()
    while index < len(text) and depth > 0:
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                break
        index += 1
    return text[match.end():index]


def _parse_capability_string(text: str) -> set[str]:
    """Extract the MCCS capability names (e.g. ``Brightness``, ``Volume``)."""
    names: set[str] = set()
    for match in re.finditer(r"\b([A-Za-z][A-Za-z0-9\- ]{1,30}?)\s*\(", text):
        names.add(match.group(1).strip())
    # vcp(...) blocks also appear as "vcp(10 12 60 ...)" hex codes.
    return names


def _supported_vcps(text: str) -> set[int]:
    """Return the VCP codes listed at the top level of the ``vcp(...)`` block."""
    block = _capability_vcp_block(text)
    codes: set[int] = set()
    depth = 0
    token = ""

    def flush() -> None:
        if depth == 0 and re.fullmatch(r"[0-9A-Fa-f]{2}", token):
            codes.add(int(token, 16))

    for char in block + " ":
        if char == "(":
            flush()               # e.g. "DC" directly before its value list
            depth += 1
            token = ""
        elif char == ")":
            depth = max(0, depth - 1)
            token = ""
        elif char.isspace() or char == ",":
            flush()
            token = ""
        else:
            token += char
    return codes


def _supported_color_modes(text: str) -> list[int]:
    """Return the VCP 0xDC values the panel advertises, in advertised order.

    BenQ panels publish an explicit value list, e.g.
    ``vcp(... DC(00 03 0F 12 27 28) ...)`` — the authoritative set of picture
    modes for that exact model.
    """
    block = _capability_vcp_block(text)
    match = re.search(r"\bDC\s*\(([^)]*)\)", block, re.IGNORECASE)
    if not match:
        return []
    values: list[int] = []
    for token in re.split(r"[\s,]+", match.group(1)):
        token = token.strip()
        if re.fullmatch(r"[0-9A-Fa-f]{1,4}", token):
            value = int(token, 16)
            if 0 <= value <= 0xFF and value not in values:
                values.append(value)
    return values


class MonitorManager:
    """Owns discovery, backend selection and per-monitor state."""

    def __init__(self, backend: DdcBackend | None = None,
                 vcp_overrides: dict[str, int] | None = None,
                 prefer_benq: bool = True) -> None:
        self._lock = threading.RLock()
        self._monitors: dict[str, MonitorState] = {}
        # MCCS capability strings are read once per display and cached: the
        # string is ~15 DDC round trips (~1 s) and never changes while a
        # monitor stays attached, so re-reading it on every poll is what made
        # the UI stutter.
        self._capabilities: dict[str, str] = {}
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
    def discover(self) -> list[MonitorState]:
        """Populate the monitor list from sysfs only — no bus traffic.

        Cheap enough (~ms) to run before the slow per-monitor probe so the UI
        can show the attached displays immediately.
        """
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
            for display_id in list(self._monitors):
                if display_id not in seen:
                    del self._monitors[display_id]
                    self._capabilities.pop(display_id, None)
            return list(self._monitors.values())

    def refresh(self, reload_capabilities: bool = False,
                on_update=None) -> list[MonitorState]:
        """Re-scan hardware and probe each monitor.

        The capability string is cached (in memory, then on disk); pass
        *reload_capabilities* (the user-facing "refresh" action) to bypass both
        and read the panel again.  *on_update* is called after each monitor's
        cheap link test so callers can publish the monitor list before the
        slow capability read finishes.  All I/O happens outside the lock so a
        reader on another thread is never blocked by a DDC round trip.
        """
        states = self.discover()
        if reload_capabilities:
            with self._lock:
                self._capabilities.clear()
        for state in states:
            self._probe(state, reload_capabilities=reload_capabilities,
                        on_update=on_update)
        return states

    def poll(self) -> list[MonitorState]:
        """Cheap periodic update: re-read live values, nothing else.

        Deliberately avoids discovery, and only reads the values the UI
        actually shows changing, so a cycle stays short and a queued user
        action is not stuck behind it for long.

        Displays that still owe a probe — a transiently dead link, or a
        capability read that failed — are re-probed on a backoff, so a flaky
        DDC/CI bus recovers instead of leaving a monitor stuck offline (or
        stuck with the generic mode list) until the next restart.
        """
        now = time.monotonic()
        with self._lock:
            states = list(self._monitors.values())
        live: list[MonitorState] = []
        retry: list[MonitorState] = []
        for state in states:
            if now >= state.retry_after:
                retry.append(state)          # link or capability read pending
            elif state.online or state.backlight:
                live.append(state)           # cheap value refresh
        for state in live:
            self._refresh_values(state, full=False)
        for state in retry:
            self._probe(state)
        return live + retry

    def _probe(self, state: MonitorState, reload_capabilities: bool = False,
               on_update=None) -> None:
        state.backend = self._backend.name
        state.backlight = self._backlight.supports(state.identity)
        # The VCP-version probe (0xDF) is the link test used by Monitor.dll.
        probe = self._backend.get_vcp(state.identity, mccs.Vcp.VCP_VERSION)
        # A display that answers but rejects 0xDF only lacks that VCP; one that
        # times out / errors has no usable DDC/CI link at all.
        link_ok = probe.supported or probe.error.startswith("result")
        state.online = link_ok
        state.error = "" if link_ok else probe.error
        if not link_ok:
            # Retry a dead link indefinitely on a backoff: a transient bus
            # failure at start-up must not leave the monitor offline.
            state.retry_after = time.monotonic() + OFFLINE_RETRY_SECONDS
        if state.backlight:
            # Internal panel: brightness comes from sysfs, independent of DDC.
            state.brightness = self._backlight.get_vcp(
                state.identity, mccs.Vcp.BRIGHTNESS)
        if on_update is not None:
            on_update()

        if not link_ok:
            # No DDC link — do not spend seconds more on this display.
            state.capability_string = ""
            state.color_modes = []
            state.capabilities = self._resolve_capabilities(state, "")
            state.probed = True
            return

        capabilities = self._capabilities.get(state.identity.display_id)
        if capabilities is None or reload_capabilities:
            capabilities = None
            if not reload_capabilities:
                capabilities = capcache.load(state.identity)
            if capabilities is None:
                capabilities = self._backend.get_capabilities(state.identity)
                capcache.store(state.identity, capabilities)
            if capabilities:
                with self._lock:
                    self._capabilities[state.identity.display_id] = capabilities
            capabilities = capabilities or ""

        if capabilities:
            state.caps_attempts = 0
            state.retry_after = NO_RETRY
        else:
            # The capability read is the flakiest DDC/CI conversation; retry it
            # a few times before falling back to the generic mode list, so a
            # one-off failure does not hide a panel's real modes for the session.
            state.caps_attempts += 1
            state.retry_after = (time.monotonic() + OFFLINE_RETRY_SECONDS
                                 if state.caps_attempts < CAPABILITY_ATTEMPTS
                                 else NO_RETRY)

        state.capability_string = capabilities
        state.color_modes = _supported_color_modes(capabilities)
        state.capabilities = self._resolve_capabilities(state, capabilities)
        self._refresh_values(state)
        # Trust the live probe when the capability string is missing or omits
        # the DC(...) value list, so the picture-mode selector is offered
        # exactly when the display actually answers VCP 0xDC.
        if state.color_mode.supported:
            state.capabilities.capabilities.add("color_mode")
        if not state.color_modes:
            state.color_modes = list(mccs.DEFAULT_COLOR_MODES)
        state.probed = True

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
        if ("Select color preset" in names or mccs.Vcp.COLOR_MODE in vcps
                or _supported_color_modes(capability_string)):
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

    def _read_value(self, state: MonitorState, attribute: str, source,
                    code: int) -> None:
        """Read one VCP into *state*, keeping the last good value on failure.

        The bus drops reads now and then; without this a transient error would
        blank a perfectly good cached value and make the UI flicker.
        """
        fresh = source.get_vcp(state.identity, code)
        if fresh.supported or not getattr(state, attribute).supported:
            setattr(state, attribute, fresh)

    def _refresh_values(self, state: MonitorState, full: bool = True) -> None:
        brightness_source = self._backlight if state.backlight else self._backend
        self._read_value(state, "brightness", brightness_source,
                         self.vcp("brightness", mccs.Vcp.BRIGHTNESS))
        if not state.online:
            # Internal panel with no DDC link: brightness is all there is.
            return
        self._read_value(state, "color_mode", self._backend,
                         self.vcp("color_mode", mccs.Vcp.COLOR_MODE))
        if not full:
            # A periodic poll only re-reads what the UI shows changing; the
            # set-points the app itself writes are updated optimistically, so
            # re-reading volume/mute/firmware every cycle is wasted bus time.
            return
        self._read_value(state, "volume", self._backend,
                         self.vcp("volume", mccs.Vcp.VOLUME))
        self._read_value(state, "mute", self._backend,
                         self.vcp("mute", mccs.Vcp.MUTE))
        self._read_value(state, "firmware", self._backend,
                         self.vcp("firmware", mccs.Vcp.FIRMWARE))

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
        """Write a picture mode over VCP 0xDC.

        BenQ panels encode the mode as a 16-bit ``(sub << 8) | value``.  Most
        modes use ``sub == 0`` but some only take a non-zero ``sub`` (on the
        GW2490, *Coding* = ``0x27`` is only accepted as ``0x0127``/``0x0227``).
        The applicable sub is not derivable from the capability string, so the
        write is confirmed with a read-back and a small ladder of sub values is
        tried.  Returns True only when the panel reports the requested mode.
        """
        with self._lock:
            state = self._monitors.get(display_id)
        if state is None:
            return False
        vcp = self.vcp("color_mode", mccs.Vcp.COLOR_MODE)
        mode &= 0xFF
        for sub in (0x00, 0x01, 0x02):
            value = (sub << 8) | mode
            ok = self._backend.set_vcp(state.identity, vcp, value)
            fresh = self._backend.get_vcp(state.identity, vcp)
            if fresh.supported:
                state.color_mode = fresh
                if (fresh.current & 0xFF) == mode:
                    return True
            elif ok:
                # No read-back channel: trust the write as before.
                state.color_mode.current = value
                state.color_mode.supported = True
                return True
        return False

    def close(self) -> None:
        with self._lock:
            try:
                self._backend.close()
            except Exception:
                pass
