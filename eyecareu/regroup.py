"""Activate freshly-granted supplemental groups without a re-login.

When ``usermod -aG i2c,video`` adds the user to the groups that carry DDC/CI
(``i2c``) and the sysfs backlight (``video``), the change only affects *new*
sessions.  A running session keeps the old supplementary group set, so the app
would still see ``EACCES`` on ``/dev/i2c-*`` until the user logs out and back in.

This module closes that gap: if the user is a member of a needed group that is
not yet active in this process, it re-executes the application through the
setuid ``sg`` helper, which switches the process group on the fly.  It runs at
most once (guarded by an environment marker) and can be disabled with
``EYECAREU_NO_REGROUP=1``.
"""

from __future__ import annotations

import grp
import os
import pwd
import shlex
import shutil
import sys

_MARKER = "EYECAREU_REGROUPED"
_DISABLE = "EYECAREU_NO_REGROUP"

# Groups that grant the hardware access this app needs.
_NEEDED_GROUPS = ("i2c", "video")


def _user_name() -> str:
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:  # pragma: no cover - extremely unusual
        return os.environ.get("USER", "")


def _pending_groups() -> list[str]:
    """Needed groups the user belongs to but that are not active here."""
    user = _user_name()
    active = set(os.getgroups()) | {os.getgid()}
    pending: list[str] = []
    for name in _NEEDED_GROUPS:
        try:
            entry = grp.getgrnam(name)
        except KeyError:
            continue
        if entry.gr_gid in active:
            continue
        members = entry.gr_mem
        if user in members or (entry.gr_gid == os.getgid()):
            pending.append(name)
    return pending


def maybe_reexec(argv: list[str] | None = None) -> None:
    """Re-exec the process with pending groups active, once.

    Never returns if the re-exec happens; returns ``None`` otherwise.
    """
    if os.environ.get(_MARKER) or os.environ.get(_DISABLE):
        return
    if os.name != "posix" or sys.platform != "linux":
        return

    pending = _pending_groups()
    if not pending:
        return

    sg = shutil.which("sg")
    if sg is None:
        return

    args = list(argv if argv is not None else sys.argv)
    # Reconstruct a portable invocation: run the package as a module so hidden
    # relative imports keep working regardless of how we were launched.
    inner_parts = [sys.executable, "-m", "eyecareu", *args[1:]]
    command = " ".join(shlex.quote(part) for part in inner_parts)
    for group in reversed(pending):
        command = f"{shlex.quote(sg)} {shlex.quote(group)} -c {shlex.quote(command)}"

    print(f"eyecareu: activating groups {', '.join(pending)} via sg", file=sys.stderr)
    env = dict(os.environ)
    env[_MARKER] = "1"
    try:
        os.execvpe("/bin/sh", ["/bin/sh", "-c", command], env)
    except OSError:
        # If anything goes wrong just continue in the current session; the app
        # will report the permission problem itself.
        return
