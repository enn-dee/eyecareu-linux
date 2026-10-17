"""Eye-CareU for Linux - a port of BenQ Eye-CareU (Windows v1.5.5.0).

The package is split into four cooperating layers:

``ddc``       DDC/CI transport (raw i2c-dev and ``ddcutil``) + monitor discovery
``display``   session/display backends (gamma, colour temperature, dimming)
``features``  eye-care features (timers, reminders, circadian, screen-time)
``core``      the ``EyeCareCore`` QObject exposed to the Qt/QML user interface

See ``README.md`` for the reverse-engineering provenance of every feature.
"""

from __future__ import annotations

from .version import __version__, WINDOWS_SOURCE_VERSION

__all__ = ["__version__", "WINDOWS_SOURCE_VERSION"]
