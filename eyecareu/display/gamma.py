"""Colour-ramp control through XRandR (X11) with ctypes.

The Windows build applied night light / low blue light / software dimming by
manipulating the gamma ramp of each display (``SetDeviceGammaRamp``).  On X11
the equivalent is the XRandR CRTC gamma ramp, which this module drives directly
through ``libX11`` / ``libXrandr`` using ctypes - no PyQt or python-xlib
dependency.

When no X11 display is reachable (Wayland, headless, or permissions missing) the
controller reports itself unavailable and every operation becomes a no-op; the
UI then falls back to the compositor's own night-light or the bundled overlay.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import math
import os
from dataclasses import dataclass

from .session import SessionType, detect_session


# --------------------------------------------------------------------------
# Colour maths
# --------------------------------------------------------------------------
def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def kelvin_to_rgb(temp: float) -> tuple[float, float, float]:
    """Approximate a blackbody colour as RGB multipliers (Tanner Helland).

    Returns three factors in the 0..1 range normalised so the brightest channel
    is 1.0, i.e. a pure tint with no unintended dimming.
    """
    temp = max(1000.0, min(40000.0, temp)) / 100.0
    if temp <= 66.0:
        red = 255.0
    else:
        red = 329.698727446 * ((temp - 60.0) ** -0.1332047592)
    if temp <= 66.0:
        green = 99.4708025861 * math.log(temp) - 161.1195681661
    else:
        green = 288.1221695283 * ((temp - 60.0) ** -0.0755148492)
    if temp >= 66.0:
        blue = 255.0
    elif temp <= 19.0:
        blue = 0.0
    else:
        blue = 138.5177312231 * math.log(temp - 10.0) - 305.0447927307
    red, green, blue = (_clamp(red / 255.0), _clamp(green / 255.0), _clamp(blue / 255.0))
    peak = max(red, green, blue, 1e-6)
    return red / peak, green / peak, blue / peak


@dataclass(slots=True)
class ColorTransform:
    """A multiplicative colour correction applied on top of the identity ramp."""

    red: float = 1.0
    green: float = 1.0
    blue: float = 1.0
    gamma: float = 1.0
    brightness: float = 1.0

    def combine(self, other: "ColorTransform") -> "ColorTransform":
        return ColorTransform(
            red=self.red * other.red,
            green=self.green * other.green,
            blue=self.blue * other.blue,
            gamma=self.gamma * other.gamma,
            brightness=self.brightness * other.brightness,
        )

    def is_identity(self) -> bool:
        return (abs(self.red - 1.0) < 1e-4 and abs(self.green - 1.0) < 1e-4
                and abs(self.blue - 1.0) < 1e-4 and abs(self.gamma - 1.0) < 1e-4
                and abs(self.brightness - 1.0) < 1e-4)

    def build_ramps(self, size: int) -> tuple[list[int], list[int], list[int]]:
        """Return three 16-bit lookup tables of *size* entries."""
        if size < 2:
            size = 2
        inv_gamma = 1.0 / self.gamma if self.gamma > 0 else 1.0
        red: list[int] = []
        green: list[int] = []
        blue: list[int] = []
        for index in range(size):
            base = index / (size - 1)
            shaped = base ** inv_gamma
            red.append(round(65535 * _clamp(shaped * self.red * self.brightness)))
            green.append(round(65535 * _clamp(shaped * self.green * self.brightness)))
            blue.append(round(65535 * _clamp(shaped * self.blue * self.brightness)))
        return red, green, blue


# --------------------------------------------------------------------------
# XRandR bindings
# --------------------------------------------------------------------------
class _XRRScreenResources(ctypes.Structure):
    _fields_ = [
        ("timestamp", ctypes.c_ulong),
        ("configTimestamp", ctypes.c_ulong),
        ("ncrtc", ctypes.c_int),
        ("crtcs", ctypes.POINTER(ctypes.c_ulong)),
        ("noutput", ctypes.c_int),
        ("outputs", ctypes.POINTER(ctypes.c_ulong)),
        ("nmode", ctypes.c_int),
        ("modes", ctypes.c_void_p),
    ]


class _XRRCrtcGamma(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_int),
        ("red", ctypes.POINTER(ctypes.c_ushort)),
        ("green", ctypes.POINTER(ctypes.c_ushort)),
        ("blue", ctypes.POINTER(ctypes.c_ushort)),
    ]


class X11GammaController:
    """Apply :class:`ColorTransform` ramps to every XRandR CRTC."""

    def __init__(self) -> None:
        self._x11 = None
        self._xrandr = None
        self._display = None
        self._screen = -1
        self._root = 0
        self._crtcs: list[int] = []
        self._crtc_gamma_size = 0
        self._available = False
        self.error = ""
        self._load()

    # -- setup -------------------------------------------------------------
    def _load(self) -> None:
        if detect_session() is not SessionType.X11 or not os.environ.get("DISPLAY"):
            self.error = "no X11 session"
            return
        x11_name = ctypes.util.find_library("X11") or "libX11.so.6"
        xrandr_name = ctypes.util.find_library("Xrandr") or "libXrandr.so.2"
        try:
            self._x11 = ctypes.CDLL(x11_name)
            self._xrandr = ctypes.CDLL(xrandr_name)
        except OSError as exc:
            self.error = f"libX11/libXrandr unavailable: {exc}"
            return
        self._bind()
        display = self._x11.XOpenDisplay(None)
        if not display:
            self.error = "cannot open X display"
            return
        self._display = display
        self._screen = self._x11.XDefaultScreen(display)
        self._root = self._x11.XRootWindow(display, self._screen)
        self._enumerate_crtcs()
        self._available = bool(self._crtcs) and self._crtc_gamma_size > 0
        if not self._available:
            self.error = "no XRandR CRTC exposes a gamma ramp"

    def _bind(self) -> None:
        x11 = self._x11
        xrandr = self._xrandr
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XDefaultScreen.restype = ctypes.c_int
        x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
        x11.XRootWindow.restype = ctypes.c_ulong
        x11.XRootWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]

        xrandr.XRRGetScreenResourcesCurrent.restype = ctypes.POINTER(_XRRScreenResources)
        xrandr.XRRGetScreenResourcesCurrent.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        xrandr.XRRFreeScreenResources.argtypes = [ctypes.POINTER(_XRRScreenResources)]
        xrandr.XRRGetCrtcGammaSize.restype = ctypes.c_int
        xrandr.XRRGetCrtcGammaSize.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        xrandr.XRRAllocGamma.restype = ctypes.POINTER(_XRRCrtcGamma)
        xrandr.XRRAllocGamma.argtypes = [ctypes.c_int]
        xrandr.XRRSetCrtcGamma.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                           ctypes.POINTER(_XRRCrtcGamma)]
        xrandr.XRRFreeGamma.argtypes = [ctypes.POINTER(_XRRCrtcGamma)]

    def _enumerate_crtcs(self) -> None:
        resources = self._xrandr.XRRGetScreenResourcesCurrent(self._display, self._root)
        if not resources:
            return
        try:
            res = resources.contents
            for index in range(res.ncrtc):
                crtc = res.crtcs[index]
                size = self._xrandr.XRRGetCrtcGammaSize(self._display, crtc)
                if size > 0:
                    self._crtcs.append(crtc)
                    self._crtc_gamma_size = max(self._crtc_gamma_size, size)
        finally:
            self._xrandr.XRRFreeScreenResources(resources)

    # -- API ---------------------------------------------------------------
    @property
    def available(self) -> bool:
        return self._available

    @property
    def gamma_size(self) -> int:
        return self._crtc_gamma_size

    def apply(self, transform: ColorTransform,
              temperature: float | None = None, dim: int = 100) -> bool:
        # X11 uses the RGB ramp transform; the temperature/dim hints are ignored
        # because they are already encoded in the transform.
        del temperature, dim
        if not self._available or self._display is None:
            return False
        size = self._crtc_gamma_size
        red, green, blue = transform.build_ramps(size)
        gamma = self._xrandr.XRRAllocGamma(size)
        if not gamma:
            return False
        try:
            for index in range(size):
                gamma.contents.red[index] = red[index]
                gamma.contents.green[index] = green[index]
                gamma.contents.blue[index] = blue[index]
            for crtc in self._crtcs:
                self._xrandr.XRRSetCrtcGamma(self._display, crtc, gamma)
            self._x11.XSync(self._display, 0)
            return True
        finally:
            self._xrandr.XRRFreeGamma(gamma)

    def reset(self) -> bool:
        return self.apply(ColorTransform())

    def close(self) -> None:
        if self._display is not None:
            try:
                self._x11.XCloseDisplay(self._display)
            except Exception:
                pass
            self._display = None
        self._available = False


class NullGammaController:
    """No-op controller used when no colour-control path exists."""

    name = "none"
    available = False
    gamma_size = 0
    error = "no colour-control path on this session"

    def apply(self, transform: ColorTransform,
              temperature: float | None = None, dim: int = 100) -> bool:
        del transform, temperature, dim
        return False

    def reset(self) -> bool:
        return False

    def close(self) -> None:
        pass


def make_controller():
    """Pick the best available colour-control backend.

    Prefers Hyprland's CTM control (real, whole-screen), then the X11 gamma
    ramp, and finally a no-op controller.
    """
    from .hyprsunset import HyprsunsetController

    hypr = HyprsunsetController()
    if hypr.available:
        return hypr
    controller = X11GammaController()
    if controller.available:
        return controller
    return NullGammaController()
