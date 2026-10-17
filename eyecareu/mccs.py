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

    * the values a BenQ panel publishes in its own capability string, e.g. the
      GW2490 reports ``vcp(... DC(00 03 0F 12 27 28) ...)`` and its spec sheet
      lists the modes *M-book, Standard, User, Game, ePaper, Care mode, Coding,
      Cinema* — so ``0x27`` is Coding and ``0x03`` is the Cinema/Movie slot.

    Video-input panels (retail BenQ TVs/monitors) use a partly different set
    (sRGB ``0x0A``, ePaper ``0x1F``, HDR ``0x23``, Dark/Light theme ``0x30/0x31``);
    those names are included so panels that advertise them get a real label.
    """

    STANDARD = 0x00
    CARE_MODE = 0x01
    CINEMA_MOVIE = 0x03      # MCCS "Movie"; used by the GW-series Cinema mode
    SRGB = 0x0A
    M_BOOK = 0x0F
    USER = 0x12
    M_PHOTO = 0x1E
    EPAPER = 0x1F
    HDR = 0x23
    CODING = 0x27
    GAME = 0x28
    DARK_THEME = 0x30
    LIGHT_THEME = 0x31
    CINEMA = 0x32


#: Human names for the VCP 0xDC values above.  A panel only ever exposes the
#: subset it advertises in its capability string, so listing the union here is
#: safe: unsupported entries are never offered.
BENQ_COLOR_MODES: dict[int, str] = {
    ColorMode.STANDARD: "Standard",
    ColorMode.CARE_MODE: "Care Mode",
    ColorMode.CINEMA_MOVIE: "Cinema",
    ColorMode.SRGB: "sRGB",
    ColorMode.M_BOOK: "M-book",
    ColorMode.USER: "User",
    ColorMode.M_PHOTO: "M-Photo",
    ColorMode.EPAPER: "ePaper",
    ColorMode.HDR: "HDR",
    ColorMode.CODING: "Coding",
    ColorMode.GAME: "Game",
    ColorMode.DARK_THEME: "Dark Theme",
    ColorMode.LIGHT_THEME: "Light Theme",
    ColorMode.CINEMA: "Cinema",
}

#: Retained for backwards compatibility with earlier revisions of this port.
COLOR_MODE_NAMES = BENQ_COLOR_MODES

#: Fallback presentation order, used only when a panel does not publish an
#: explicit ``DC(...)`` value list in its capability string.
DEFAULT_COLOR_MODES: tuple[int, ...] = (
    ColorMode.STANDARD,
    ColorMode.CINEMA_MOVIE,
    ColorMode.CODING,
    ColorMode.GAME,
    ColorMode.M_BOOK,
    ColorMode.USER,
    ColorMode.EPAPER,
    ColorMode.CARE_MODE,
    ColorMode.SRGB,
    ColorMode.HDR,
    ColorMode.CINEMA,
    ColorMode.DARK_THEME,
    ColorMode.LIGHT_THEME,
    ColorMode.M_PHOTO,
)


def color_mode_name(value: int) -> str:
    """Return the human name for a VCP 0xDC value, or ``Mode 0xNN``."""
    code = int(value) & 0xFF
    return BENQ_COLOR_MODES.get(code, f"Mode 0x{code:02X}")

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
