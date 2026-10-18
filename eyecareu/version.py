"""Version and provenance metadata for the Eye-CareU Linux port."""

from __future__ import annotations

__all__ = ["__version__", "WINDOWS_SOURCE_VERSION", "APP_NAME", "APP_ID", "ORG_NAME"]

#: Version of this Linux port.
__version__ = "1.0.1"

#: The Windows release this port reproduces.
WINDOWS_SOURCE_VERSION = "1.5.5.0"

APP_NAME = "Eye-CareU"
APP_ID = "io.github.eyecareu.Linux"
ORG_NAME = "Eye-CareU"

#: Leaked build directory recovered from the shipped ``Eye-CareU.exe``
#: (recorded for provenance; not used at runtime).
WINDOWS_BUILD_PATH = "D:/01_program/EyeCare/setup/win64/build/bin"
