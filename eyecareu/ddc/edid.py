"""Minimal EDID parser used for monitor discovery and display naming."""

from __future__ import annotations

import struct

_EDID_HEADER = b"\x00\xff\xff\xff\xff\xff\xff\x00"

# Common PNP manufacturer ids (enough to label the panel nicely).
PNP_NAMES: dict[str, str] = {
    "BNQ": "BenQ",
    "DEL": "Dell",
    "SAM": "Samsung",
    "GSM": "LG",
    "LGD": "LG Display",
    "ACR": "Acer",
    "AUS": "ASUS",
    "HWP": "HP",
    "LEN": "Lenovo",
    "PHL": "Philips",
    "AOC": "AOC",
    "VSC": "ViewSonic",
    "MSI": "MSI",
    "GBT": "Gigabyte",
    "IVM": "Iiyama",
    "ELE": "Element",
}


def _pnp_id(raw: bytes) -> str:
    if len(raw) < 2:
        return ""
    value = (raw[0] << 8) | raw[1]
    letters = [chr(((value >> shift) & 0x1F) + 0x40) for shift in (10, 5, 0)]
    return "".join(letters)


def _descriptor_text(block: bytes) -> str:
    """Decode a monitor-name / serial descriptor string from an 18-byte block."""
    if len(block) < 18 or block[0:3] != b"\x00\x00\x00":
        return ""
    if block[3] not in (0xFC, 0xFE, 0xFF):  # name / string / serial
        return ""
    text = block[5:18].split(b"\x0a")[0]
    return text.decode("ascii", "ignore").strip()


def parse_edid(data: bytes) -> dict:
    """Parse the base EDID block and return a dict of display attributes."""
    out: dict = {
        "valid": False, "manufacturer": "", "product_code": 0,
        "serial": "", "model": "", "year": 0, "width_mm": 0, "height_mm": 0,
    }
    if len(data) < 128 or data[:8] != _EDID_HEADER:
        return out
    out["valid"] = True
    out["manufacturer"] = _pnp_id(data[8:10])
    out["product_code"] = struct.unpack("<H", data[10:12])[0]
    serial_le = struct.unpack("<I", data[12:16])[0]
    out["year"] = 1990 + data[17] if data[17] else 0
    out["width_mm"] = data[21] * 10
    out["height_mm"] = data[22] * 10

    serial_text = ""
    name = ""
    for offset in (54, 72, 90, 108):
        block = data[offset:offset + 18]
        if len(block) < 18:
            continue
        if block[3] == 0xFC:
            name = name or _descriptor_text(block)
        elif block[3] == 0xFF:
            serial_text = serial_text or _descriptor_text(block)
    out["model"] = name
    out["serial"] = serial_text or (str(serial_le) if serial_le not in (0, 0xFFFFFFFF) else "")
    return out


def manufacturer_name(pnp_id: str) -> str:
    return PNP_NAMES.get(pnp_id.upper(), "")
