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
    """Picture modes for VCP 0xDC.

    Recovered from the embedded model schemas (``VCPTree`` documents in
    ``Eye-CareU.exe``)::

        <VCPcode Type="Standard"  Category="Picture Mode" Code="0x00" SHCode="0x00"/>
        <VCPcode Type="Cinema"    Category="Picture Mode" Code="0x32" SHCode="0x00"/>
        <VCPcode Type="Game"      Category="Picture Mode" Code="0x28" SHCode="0x00"/>
        <VCPcode Type="Care Mode" Category="Picture Mode" Code="0x01" SHCode="0x00"/>
    """

    STANDARD = 0x00
    CINEMA = 0x32
    GAME = 0x28
    CARE_MODE = 0x01
    # MCCS-standard extras, offered when a monitor advertises them.
    SRGB = 0x0F
    USER = 0x1F
    M_PHOTO = 0x1E
    DYNAMIC = 0x03


COLOR_MODE_NAMES: dict[int, str] = {
    ColorMode.STANDARD: "Standard",
    ColorMode.CINEMA: "Cinema",
    ColorMode.GAME: "Game",
    ColorMode.CARE_MODE: "Care Mode",
    ColorMode.SRGB: "sRGB",
    ColorMode.USER: "User",
    ColorMode.M_PHOTO: "M-Photo",
    ColorMode.DYNAMIC: "Dynamic",
}

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
