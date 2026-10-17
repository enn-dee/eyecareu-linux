#!/usr/bin/env python3
"""Interactively identify a BenQ panel's VCP 0xDC picture-mode values.

DDC/CI can *read* the stored VCP 0xDC value but the value is an opaque number:
the mode *name* it corresponds to only appears in the monitor's own OSD banner.
This tool writes each known/possible value and lets you record the name the
panel shows, then prints a ready-to-paste Python mapping.

Usage::

    sudo -v                                   # or be in the "i2c" group
    python3 tools/identify_color_modes.py

Nothing is written to the repository; the mapping is printed to stdout.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eyecareu.ddc.discovery import discover_monitors
from eyecareu.ddc.i2c import I2cDdcBackend

# Full 16-bit VCP 0xDC values worth checking.  BenQ encodes a "sub" byte in the
# high half: the panel's capability string advertises the low byte 0x27, but the
# GW2490 only accepts it as 0x0127 / 0x0227 / 0x0427.
CANDIDATES = [
    0x0000, 0x000F, 0x0012, 0x0028, 0x0032,
    0x0127, 0x0227, 0x0427,
]


def main() -> int:
    monitors = [m for m in discover_monitors()
                if m.is_benq and m.i2c_bus is not None]
    if not monitors:
        print("No BenQ monitor with a DDC/CI bus found.")
        return 1
    monitor = monitors[0]
    backend = I2cDdcBackend()
    vcp = 0xDC

    print(f"Monitor: {monitor.label}  (bus {monitor.i2c_bus})")
    print("For each value: press Enter to apply it, then read the mode name")
    print("shown by the monitor's own OSD banner and type it in.")
    print("Leave the name blank to skip a value.\n")

    found: list[tuple[int, str]] = []
    for value in CANDIDATES:
        try:
            input(f"-- value 0x{value:04X}: press Enter to apply... ")
        except EOFError:
            break
        backend.set_vcp(monitor, vcp, value)
        try:
            name = input(f"   0x{value:04X} applied. Mode name shown: ").strip()
        except EOFError:
            name = ""
        if name:
            found.append((value, name))

    print("\n# --- paste into eyecareu/mccs.py ---")
    for value, name in found:
        print(f"    0x{value:04X}: {name!r},")

    # Leave the panel on Standard.
    backend.set_vcp(monitor, vcp, 0x0000)
    backend.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
