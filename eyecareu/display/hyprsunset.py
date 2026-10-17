"""Real colour-temperature and dimming control on Hyprland via ``hyprsunset``.

Hyprland implements the ``hyprland-ctm-control-v1`` protocol: a client can set a
colour transformation matrix that the compositor applies to each output.  The
``hyprsunset`` utility is the reference client for it, and Hyprland's IPC lets us
steer it with::

    hyprctl hyprsunset temperature 3400     # colour temperature (K)
    hyprctl hyprsunset gamma 60             # output gamma % (dimming)
    hyprctl hyprsunset identity true        # reset to neutral

This is a *real* whole-screen colour change (not an overlay), so night light,
low blue light, warm tint, circadian mode and software dimming all work on
Wayland/Hyprland.  The controller starts the ``hyprsunset`` daemon if it is not
already running and only stops it again if it started it.

On compositors without this protocol (or without ``hyprsunset`` installed) the
controller reports itself unavailable and the caller falls back.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

_NEUTRAL_TEMPERATURE = 6500.0


def is_hyprland() -> bool:
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return True
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()
    return "hyprland" in desktop


def hyprctl_path() -> str | None:
    return shutil.which("hyprctl")


def _runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or ""
    return Path(base) / "hypr" / signature


class HyprsunsetController:
    """Drives Hyprland's colour transformation matrix through ``hyprsunset``."""

    name = "hyprsunset"

    def __init__(self, command: str | None = None) -> None:
        self._hyprctl = command or hyprctl_path() or "hyprctl"
        self._proc: subprocess.Popen | None = None
        self._own_daemon = False
        self.available = False
        self.error = ""
        self._last: tuple[int, int] | None = None
        self._dirty = False
        self._probe()

    # -- setup -------------------------------------------------------------
    def _probe(self) -> None:
        if not is_hyprland():
            self.error = "not a Hyprland session"
            return
        if shutil.which("hyprctl") is None:
            self.error = "hyprctl not found"
            return
        already_running = self._socket().exists()
        if not self._ensure_daemon():
            return
        if not already_running:
            # We just started it; it boots at 5000 K, so neutralise it.  When a
            # daemon was already running we leave its state untouched.
            self._call("gamma", "100")
            code, out, err = self._call("identity", "true")
            if code != 0:
                self.error = (err or out or "hyprsunset did not answer").strip()
                return
        self.available = True

    def _socket(self) -> Path:
        return _runtime_dir() / ".hyprsunset.sock"

    def _ensure_daemon(self) -> bool:
        if self._socket().exists():
            return True
        if shutil.which("hyprsunset") is None:
            self.error = "hyprsunset is not installed"
            return False
        try:
            self._proc = subprocess.Popen(
                ["hyprsunset"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            self.error = f"could not start hyprsunset: {exc}"
            return False
        self._own_daemon = True
        for _ in range(40):
            if self._socket().exists():
                return True
            time.sleep(0.05)
        self.error = "hyprsunset did not create its socket"
        return False

    # -- IPC ---------------------------------------------------------------
    def _call(self, *args: str) -> tuple[int, str, str]:
        try:
            proc = subprocess.run(
                [self._hyprctl, "hyprsunset", *args],
                capture_output=True, text=True, timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, "", str(exc)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

    # -- controller API ----------------------------------------------------
    def apply(self, transform, temperature: float | None, dim: int) -> bool:
        if not self.available:
            return False
        temp = _NEUTRAL_TEMPERATURE if temperature is None else float(temperature)
        temp = max(1000.0, min(20000.0, temp))
        gamma = max(1, min(100, int(dim)))
        if temp >= _NEUTRAL_TEMPERATURE and gamma >= 100:
            return self.reset()
        if self._last == (round(temp), gamma):
            return True
        ok_temp, _, _ = self._call("temperature", str(round(temp)))
        ok_gamma, _, _ = self._call("gamma", str(gamma))
        ok = ok_temp == 0 and ok_gamma == 0
        if ok:
            self._last = (round(temp), gamma)
            self._dirty = True
        return ok

    def reset(self) -> bool:
        if not self.available:
            return False
        self._last = None
        # ``identity`` only clears the colour matrix, not the gamma factor, so
        # clear the gamma explicitly as well.
        self._call("gamma", "100")
        code, _, _ = self._call("identity", "true")
        return code == 0

    def close(self) -> None:
        try:
            if self.available and self._dirty:
                self.reset()
                self._dirty = False
        finally:
            if self._own_daemon and self._proc is not None:
                try:
                    self._proc.terminate()
                except OSError:
                    pass
                self._proc = None
        self.available = False


def available() -> bool:
    return is_hyprland() and shutil.which("hyprctl") is not None
