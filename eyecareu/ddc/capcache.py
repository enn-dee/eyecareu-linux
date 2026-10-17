"""On-disk cache of MCCS capability strings.

Reading a panel's capability string is by far the most expensive DDC/CI
conversation — a dozen-plus round trips, and on some BenQ firmware the reply
frames arrive stale/misaligned so each chunk costs several retries (seconds in
total).  The answer never changes for a given panel, so it is cached here,
keyed by the monitor's EDID, and every start after the first is instant.

The user-facing "refresh displays" action bypasses this cache and re-reads the
panel directly, which also replaces the cached copy.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..config import state_dir
from .base import MonitorIdentity


def _cache_path(identity: MonitorIdentity) -> Path:
    # EDID identifies the physical panel; fall back to the connector key when a
    # monitor exposes no EDID.
    material = identity.edid or identity.display_id.encode("utf-8")
    digest = hashlib.sha1(material).hexdigest()[:16]
    return state_dir() / "capabilities" / f"{identity.display_id}-{digest}.txt"


def load(identity: MonitorIdentity) -> str | None:
    """Return the cached capability string, or None when not cached."""
    try:
        text = _cache_path(identity).read_text(encoding="utf-8")
    except OSError:
        return None
    return text or None


def store(identity: MonitorIdentity, capabilities: str) -> None:
    """Persist a successfully read capability string (best effort)."""
    if not capabilities:
        return
    path = _cache_path(identity)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(capabilities, encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
