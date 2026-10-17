"""``eyecareu --doctor``: print a self-contained diagnosis of the session.

Reports which colour-control backend is available, whether the user's groups
grant hardware access, and what each detected monitor answers over DDC/CI.
Read-only: it never changes hardware state.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys

from . import mccs
from .ddc.manager import MonitorManager


def _mark(ok: bool) -> str:
    return "OK  " if ok else "FAIL"


def _active_groups() -> str:
    import grp

    names = []
    for gid in sorted(set(os.getgroups()) | {os.getgid()}):
        try:
            names.append(grp.getgrgid(gid).gr_name)
        except KeyError:
            names.append(str(gid))
    return ", ".join(names)


def _group_access() -> dict[str, bool]:
    import grp

    user = os.environ.get("USER", "")
    result: dict[str, bool] = {}
    active = set(os.getgroups())
    for name in ("i2c", "video"):
        try:
            entry = grp.getgrnam(name)
        except KeyError:
            result[name] = False
            continue
        member = user in entry.gr_mem
        result[name] = member and entry.gr_gid in active
    return result


def _effects_backend() -> tuple[str, str]:
    """Return (backend_name, note) without changing any state."""
    from .display.hyprsunset import is_hyprland

    if is_hyprland() and shutil.which("hyprctl") and shutil.which("hyprsunset"):
        return "hyprsunset", "Hyprland CTM (real, whole-screen colour + gamma)"
    if is_hyprland():
        return "overlay", "Hyprland detected but hyprsunset/hyprctl missing"
    if os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        return "overlay", "generic Wayland: only a translucent overlay is possible"
    if os.environ.get("DISPLAY"):
        return "gamma", "X11 gamma ramps"
    return "none", "no display detected"


def run() -> int:
    print("Eye-CareU for Linux - doctor")
    print("=" * 60)
    print(f"platform      : {platform.platform()}")
    print(f"python        : {sys.version.split()[0]}")
    print(f"session type  : {os.environ.get('XDG_SESSION_TYPE', '?')}")
    print(f"desktop       : {os.environ.get('XDG_CURRENT_DESKTOP', '?')}")
    print(f"wayland       : {os.environ.get('WAYLAND_DISPLAY', '-')}")
    print(f"x11 display   : {os.environ.get('DISPLAY', '-')}")

    backend, note = _effects_backend()
    print(f"\ncolour backend: {backend}")
    print(f"  note        : {note}")
    if backend == "overlay":
        print("  warning     : real colour control unavailable; install hyprsunset"
              " or run a session with gamma control")

    access = _group_access()
    print(f"\ngroups        : {_active_groups()}")
    for group, ok in access.items():
        print(f"  {group:<10}  : {_mark(ok)}")
    if not all(access.values()):
        print("  hint        : a logout/login applies new group membership; the app"
              " also re-execs through 'sg' automatically")

    print("\nmonitors")
    print("-" * 60)
    manager = MonitorManager()
    try:
        states = manager.refresh()
        if not states:
            print("  none detected")
        for state in states:
            ident = state.identity
            print(f"  {ident.display_id}  {ident.label}")
            print(f"     bus        : {ident.i2c_bus}")
            print(f"     backend    : {state.backend or '-'}"
                  f"{'  (sysfs backlight)' if state.backlight else ''}")
            print(f"     online     : {_mark(state.online)}")
            if state.error:
                print(f"     error      : {state.error}")
            for label, value in (("brightness", state.brightness),
                                 ("volume", state.volume),
                                 ("mute", state.mute),
                                 ("colour mode", state.color_mode),
                                 ("firmware", state.firmware)):
                if value.supported:
                    print(f"     {label:<11}: {value.current}/{value.maximum}"
                          f"  ({value.percent}%)")
                else:
                    detail = f"  ({value.error})" if value.error else ""
                    print(f"     {label:<11}: unsupported{detail}")
            if state.color_modes:
                modes = ", ".join(f"0x{code:04X}={mccs.color_mode_name(code)}"
                                  for code in state.color_modes)
                print(f"     modes      : {modes}")
    finally:
        manager.close()

    print("\n" + "=" * 60)
    print("done")
    return 0
