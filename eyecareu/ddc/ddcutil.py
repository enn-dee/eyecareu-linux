"""Optional DDC/CI backend delegating to the ``ddcutil`` command line tool.

``ddcutil`` is the mature userspace DDC/CI implementation on Linux and handles
some panels / adapters better than a raw ``i2c-dev`` transaction.  When it is
installed the port prefers it, and falls back to the built-in i2c backend
otherwise.
"""

from __future__ import annotations

import re
import shutil
import subprocess

from .base import DdcBackend, MonitorIdentity, VcpValue

_TIMEOUT = 12


class DdcutilBackend(DdcBackend):
    """DDC/CI backend backed by the ``ddcutil`` executable."""

    name = "ddcutil"

    def __init__(self, executable: str = "ddcutil") -> None:
        self.executable = executable
        # display_id -> ddcutil display number ("1", "2", ...)
        self._numbers: dict[str, str] = {}

    @staticmethod
    def available() -> bool:
        return shutil.which("ddcutil") is not None

    # -- helpers -----------------------------------------------------------
    def _run(self, *args: str) -> tuple[int, str, str]:
        try:
            proc = subprocess.run(
                [self.executable, *args],
                capture_output=True, text=True, timeout=_TIMEOUT, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, "", str(exc)
        return proc.returncode, proc.stdout, proc.stderr

    def _display_number(self, monitor: MonitorIdentity) -> str:
        if monitor.display_id in self._numbers:
            return self._numbers[monitor.display_id]
        _, out, _ = self._run("detect", "--brief")
        current = None
        index = 0
        for line in out.splitlines():
            match = re.match(r"Display\s+(\d+)", line)
            if match:
                index += 1
                current = str(index)
            if "I2C bus" in line and monitor.i2c_bus is not None:
                if f"i2c-{monitor.i2c_bus}" in line and current:
                    self._numbers[monitor.display_id] = current
                    return current
            if monitor.model and monitor.model in line and current:
                self._numbers[monitor.display_id] = current
                return current
        return "1"

    # -- DdcBackend --------------------------------------------------------
    def get_vcp(self, monitor: MonitorIdentity, vcp: int) -> VcpValue:
        number = self._display_number(monitor)
        code, out, err = self._run(
            "getvcp", f"0x{vcp:02X}", "--display", number, "--brief"
        )
        # Brief output: "VCP 10 C 50 100"  (hex code, type C/NC, cur, max)
        match = re.search(r"VCP\s+([0-9A-Fa-f]{2})\s+(\S+)\s+(\d+)\s+(\d+)", out)
        if not match:
            message = (err or out).strip().splitlines()
            return VcpValue(vcp=vcp, error=message[0] if message else "getvcp failed")
        _code, _type, current, maximum = match.groups()
        return VcpValue(vcp=vcp, current=int(current), maximum=int(maximum),
                        supported=True)

    def set_vcp(self, monitor: MonitorIdentity, vcp: int, value: int) -> bool:
        number = self._display_number(monitor)
        code, _out, _err = self._run(
            "setvcp", f"0x{vcp:02X}", str(int(value)), "--display", number
        )
        return code == 0

    def get_capabilities(self, monitor: MonitorIdentity) -> str:
        number = self._display_number(monitor)
        _code, out, _err = self._run("capabilities", "--display", number)
        return out
