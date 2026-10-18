"""MCCS / DDC-CI Virtual Control Panel (VCP) code definitions.

The numeric codes below were recovered from the Windows *BenQ Eye-CareU
v1.5.5.0* build by reverse engineering, and cross-checked against the public
VESA MCCS 2.1 standard.  Provenance for each code is recorded so the port keeps
observed facts separate from convention.

Reverse-engineering provenance (REA + objdump of the shipped PE32+ binaries):

  Monitor.dll  MonitorModel::getBrightness   -> getVCP(0x10)
  Monitor.dll  MonitorModel::setBrightness   -> setVCP(0x10, ...)
  Monitor.dll  MonitorModel::getVolume       -> getVCP(0x62)
  Monitor.dll  MonitorModel::setVolume       -> setVCP(0x62, ...)
  Monitor.dll  MonitorModel::getMute         -> getVCP(0x8D); value == 1 -> muted
  Monitor.dll  MonitorModel::setMute         -> setVCP(0x8D, 1/2)
  Monitor.dll  MonitorModel::getColorMode    -> getVCP(0xDC); hi<<8 | lo
  Monitor.dll  MonitorModel::setColorMode    -> setVCP(0xDC, (sub<<8)|mode)
  Monitor.dll  MonitorModel::getOsdLock/...  -> getVCP(0xCA)
  Monitor.dll  MonitorModel::setOsdLock      -> setVCP(0xCA, ...)
  Monitor.dll  MonitorModel::getFirmwareVersion -> getVCP(0xC9)
  Monitor.dll  MonitorModel::getPictureBlank -> getVCP(0xF6)
  Monitor.dll  MonitorModel::vcpTest         -> getVCP(0xDF) (VCP version probe)
  EcShared.dll reset paths                   -> setVCP(0x04/0x08, 1)

Values not directly observed in the binaries are marked as MCCS-standard
convention and are safe defaults, not claims about BenQ behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Vcp(IntEnum):
    """Virtual Control Panel codes used by the Eye-Care feature set."""

    # --- observed in Monitor.dll / EcShared.dll ---------------------------
    BRIGHTNESS = 0x10
    VOLUME = 0x62
    MUTE = 0x8D
    COLOR_MODE = 0xDC  # MCCS "Display Application" (picture / colour preset)
    OSD = 0xCA  # OSD lock / status
    FIRMWARE = 0xC9  # firmware / display controller version
    PICTURE_BLANK = 0xF6
    VCP_VERSION = 0xDF  # used as a DDC link probe
    RESET_FACTORY_COLOR = 0x04
    RESET_FACTORY_ALL = 0x08

    # --- MCCS-standard convention (not observed in the Windows build) -----
    CONTRAST = 0x12
    INPUT_SOURCE = 0x60
    POWER_MODE = 0xD6
    SHARPNESS = 0x87
    RED_GAIN = 0x16
    GREEN_GAIN = 0x18
    BLUE_GAIN = 0x1A
    # Vendor-specific block used by BenQ Brightness-Intelligence panels.
    # The Windows schema only declares *support* for these; the exact code is
    # configured per model.  Defaults follow the BenQ E-series convention.
    BENQ_BI = 0xE3
    BENQ_LOW_BLUE_LIGHT = 0xE9
    BENQ_LOW_LIGHT_SENSOR = 0xEB


VCP_NAMES: dict[int, str] = {
    Vcp.BRIGHTNESS: "Brightness",
    Vcp.CONTRAST: "Contrast",
    Vcp.VOLUME: "Volume",
    Vcp.MUTE: "Mute",
    Vcp.COLOR_MODE: "Colour Mode",
    Vcp.OSD: "OSD",
    Vcp.FIRMWARE: "Firmware",
    Vcp.PICTURE_BLANK: "Picture Blank",
    Vcp.INPUT_SOURCE: "Input Source",
    Vcp.POWER_MODE: "Power Mode",
    Vcp.SHARPNESS: "Sharpness",
    Vcp.BENQ_BI: "Brightness Intelligence",
    Vcp.BENQ_LOW_BLUE_LIGHT: "Low Blue Light",
    Vcp.BENQ_LOW_LIGHT_SENSOR: "Ambient Light Sensor",
}


class ColorMode(IntEnum):
    """Picture / colour modes for VCP 0xDC (BenQ enumeration).

    Two independent sources were combined:

    * the embedded model schemas (``VCPTree`` documents in ``Eye-CareU.exe``)::

          <VCPcode Type="Standard"  Category="Picture Mode" Code="0x00" SHCode="0x00"/>
          <VCPcode Type="Cinema"    Category="Picture Mode" Code="0x32" SHCode="0x00"/>
          <VCPcode Type="Game"      Category="Picture Mode" Code="0x28" SHCode="0x00"/>
          <VCPcode Type="Care Mode" Category="Picture Mode" Code="0x01" SHCode="0x00"/>

      plus the community reference for BenQ panels (Standard ``0x00``, sRGB
      ``0x0A``, M-book ``0x0F``, User ``0x12``, ePaper ``0x1F``, HDR ``0x23``,
      Dark/Light theme ``0x30``/``0x31``, Cinema ``0x32``).  Note that Cinema
      is ``0x32``, *not* the plain ``0x03`` some panels advertise.

    * the values a BenQ panel itself accepts, measured on a GW2490.  BenQ
      encodes some modes as a 16-bit ``(SHCode << 8) | Code`` value: the panel
      advertises only the low byte ``0x27`` in its capability string but stores
      the real modes under ``0x0127`` / ``0x0227`` / ``0x0427`` — the values the
      Windows schema calls ``SHCode``.

    A panel only ever exposes the subset it supports, so listing the union here
    is safe: unsupported entries are never offered.
    """

    STANDARD = 0x0000
    CARE_MODE = 0x0001       # panels that expose Care Mode as a plain code
    SRGB = 0x000A
    M_BOOK = 0x000F
    USER = 0x0012
    M_PHOTO = 0x001E
    EPAPER = 0x001F          # panels that expose ePaper as a plain code
    HDR = 0x0023
    GAME = 0x0028
    DARK_THEME = 0x0030
    LIGHT_THEME = 0x0031
    CINEMA = 0x0032
    # "SHCode" modes: the real mode is carried in the high half of the value.
    CARE_MODE_SHC = 0x0127   # GW-series: the panel's Care Mode
    CODING_SHC = 0x0227      # GW-series: Coding Mode
    EPAPER_SHC = 0x0427      # GW-series: ePaper Mode


#: Human names for the VCP 0xDC values above, keyed by the *full* 16-bit value
#: (which equals the plain code for modes that use the low byte only).  A panel
#: only ever exposes the subset it advertises, so the union is safe.
BENQ_COLOR_MODES: dict[int, str] = {
    ColorMode.STANDARD: "Standard",
    ColorMode.CARE_MODE: "Care Mode",
    ColorMode.SRGB: "sRGB",
    ColorMode.M_BOOK: "M-book",
    ColorMode.USER: "User",
    ColorMode.M_PHOTO: "M-Photo",
    ColorMode.EPAPER: "ePaper",
    ColorMode.HDR: "HDR",
    ColorMode.GAME: "Game",
    ColorMode.DARK_THEME: "Dark Theme",
    ColorMode.LIGHT_THEME: "Light Theme",
    ColorMode.CINEMA: "Cinema",
    ColorMode.CARE_MODE_SHC: "Care Mode",
    ColorMode.CODING_SHC: "Coding",
    ColorMode.EPAPER_SHC: "ePaper",
}

#: Retained for backwards compatibility with earlier revisions of this port.
COLOR_MODE_NAMES = BENQ_COLOR_MODES

#: Some panels publish only the low byte of a picture mode in their capability
#: string but require the mode's "SHCode" in the high half on a write.  Code
#: ``0x27`` on the GW2490 expands to these three distinct real modes.
COLOR_MODE_EXPANSION: dict[int, tuple[int, ...]] = {
    0x27: (ColorMode.CARE_MODE_SHC, ColorMode.CODING_SHC, ColorMode.EPAPER_SHC),
}

#: Per-model picture-mode lists, used where the panel's own capability string is
#: not trustworthy.  The GW2490 advertises ``DC(00 03 0F 12 27 28)`` yet
#: *rejects* ``0x03`` and *accepts* ``0x32`` (Cinema), which the string omits —
#: so a verified explicit list is used instead.  This is the local equivalent of
#: the per-model ``VCPTree`` schema the Windows application loads for a model.
MODEL_COLOR_MODES: dict[str, tuple[int, ...]] = {
    "GW2490": (
        ColorMode.STANDARD,
        ColorMode.CINEMA,
        ColorMode.GAME,
        ColorMode.EPAPER_SHC,
        ColorMode.CARE_MODE_SHC,
        ColorMode.CODING_SHC,
        ColorMode.M_BOOK,
        ColorMode.USER,
    ),
}

#: Fallback presentation order, used only when a panel publishes neither an
#: explicit ``DC(...)`` value list nor a known-model entry.
DEFAULT_COLOR_MODES: tuple[int, ...] = (
    ColorMode.STANDARD,
    ColorMode.CINEMA,
    ColorMode.GAME,
    ColorMode.M_BOOK,
    ColorMode.USER,
    ColorMode.EPAPER,
    ColorMode.CARE_MODE,
    ColorMode.SRGB,
    ColorMode.HDR,
    ColorMode.DARK_THEME,
    ColorMode.LIGHT_THEME,
    ColorMode.M_PHOTO,
)


def model_color_modes(model: str) -> tuple[int, ...] | None:
    """Verified picture-mode values for an EDID *model*, if one is recorded.

    The EDID model string usually carries the vendor name too ("BenQ GW2490"),
    so a known model name contained in it also matches.
    """
    key = (model or "").strip().upper()
    if not key:
        return None
    exact = MODEL_COLOR_MODES.get(key)
    if exact is not None:
        return exact
    for name, modes in MODEL_COLOR_MODES.items():
        if name in key:
            return modes
    return None


def expand_color_mode(code: int) -> tuple[int, ...]:
    """Expand an advertised low-byte mode *code* into full 16-bit values.

    Returns ``(code,)`` unchanged for codes that are already a complete value.
    """
    code &= 0xFF
    return tuple(int(value) for value in COLOR_MODE_EXPANSION.get(code, (code,)))


def color_mode_name(value: int) -> str:
    """Return the human name for a VCP 0xDC value, or ``Mode 0x..``."""
    value = int(value) & 0xFFFF
    name = BENQ_COLOR_MODES.get(value)
    if name is not None:
        return name
    width = 2 if value <= 0xFF else 4
    return f"Mode 0x{value:0{width}X}"

# MCCS "Get VCP Feature Reply" result codes.
RESULT_OK = 0x00
RESULT_UNSUPPORTED = 0x01
RESULT_ERROR = 0xFF

# DDC/CI status codes in the "Get VCP Feature Reply" result byte.
DDC_RESULT_TEXT: dict[int, str] = {
    0x00: "No error",
    0x01: "Unsupported VCP code",
}


@dataclass(slots=True)
class VcpReply:
    """Parsed ``Get VCP Feature Reply`` payload."""

    vcp: int
    type: int
    maximum: int
    current: int

    @property
    def percent(self) -> float:
        if self.maximum <= 0:
            return 0.0
        return (self.current / self.maximum) * 100.0


def is_supported(vcp: int, supported_codes: set[int]) -> bool:
    """Return True when *vcp* appears in the monitor capability string."""
    return vcp in supported_codes
