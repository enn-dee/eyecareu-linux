"""Display / session layer: gamma ramps and software eye-care effects."""

from __future__ import annotations

from .effects import (
    DisplayEffects,
    hyprsunset_params,
    overlay_color,
    overlay_rgba_string,
    transform_for,
)
from .gamma import (
    ColorTransform,
    NullGammaController,
    X11GammaController,
    kelvin_to_rgb,
    make_controller,
)
from .hyprsunset import HyprsunsetController, is_hyprland
from .session import (
    DisplayOutput,
    SessionType,
    detect_session,
    list_outputs,
)

__all__ = [
    "DisplayEffects",
    "transform_for",
    "overlay_color",
    "overlay_rgba_string",
    "hyprsunset_params",
    "HyprsunsetController",
    "is_hyprland",
    "ColorTransform",
    "X11GammaController",
    "NullGammaController",
    "make_controller",
    "kelvin_to_rgb",
    "DisplayOutput",
    "SessionType",
    "detect_session",
    "list_outputs",
]
