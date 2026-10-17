"""Software eye-care effects built on the colour-ramp controller.

These reproduce the Windows build's *display* effects, which do not depend on
DDC/CI and therefore work on any panel:

``night_light``        warm the whole screen toward a target colour temperature
``low_blue_light``     attenuate the blue channel by a percentage
``software_dimming``   scale the whole ramp down (dim below the monitor minimum)
``warm_tint``          a gentle fixed warm shift
``cleartype``          a subtle gamma/contrast change for text legibility

Each contributes a :class:`~eyecareu.display.gamma.ColorTransform`; the enabled
effects are multiplied together and pushed to every display in one call so the
ramps never disagree between monitors.
"""

from __future__ import annotations

from ..config import EffectSettings
from .gamma import ColorTransform, kelvin_to_rgb, make_controller


def night_light_transform(temp: float, strength: int) -> ColorTransform:
    red, green, blue = kelvin_to_rgb(temp)
    factor = max(0.0, min(1.0, strength / 100.0))
    return ColorTransform(
        red=1.0 - (1.0 - red) * factor,
        green=1.0 - (1.0 - green) * factor,
        blue=1.0 - (1.0 - blue) * factor,
    )


def low_blue_light_transform(level: int) -> ColorTransform:
    # Full strength removes ~65% of blue, matching the Windows slider range.
    reduction = max(0, min(100, level)) / 100.0 * 0.65
    return ColorTransform(blue=1.0 - reduction)


def software_dimming_transform(level: int) -> ColorTransform:
    level = max(5, min(100, level))
    return ColorTransform(brightness=level / 100.0)


def warm_tint_transform(strength: int) -> ColorTransform:
    factor = max(0, min(100, strength)) / 100.0
    return ColorTransform(
        red=1.0,
        green=1.0 - 0.10 * factor,
        blue=1.0 - 0.22 * factor,
    )


def cleartype_transform() -> ColorTransform:
    # A mild contrast boost via gamma < 1 (darkens mid-tones slightly).
    return ColorTransform(gamma=0.90, brightness=1.02)


# --------------------------------------------------------------------------
# Overlay fallback (Wayland and any session without colour-ramp control)
# --------------------------------------------------------------------------
def _over(dst: tuple[float, float, float, float],
          src: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Porter-Duff "source over" compositing of two RGBA layers."""
    dr, dg, db, da = dst
    sr, sg, sb, sa = src
    out_a = sa + da * (1.0 - sa)
    if out_a <= 1e-6:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        (sr * sa + dr * da * (1.0 - sa)) / out_a,
        (sg * sa + dg * da * (1.0 - sa)) / out_a,
        (sb * sa + db * da * (1.0 - sa)) / out_a,
        out_a,
    )


def overlay_color(settings: EffectSettings,
                  circadian_temperature: float | None = None
                  ) -> tuple[float, float, float, float] | None:
    """Represent the enabled effects as a translucent full-screen wash.

    Used when the session has no colour-ramp API (notably Wayland).  A warm
    amber layer warms the screen; a black layer dims it.  Returns ``(r, g, b,
    a)`` with components in 0..1, or ``None`` when nothing is enabled.
    """
    layer: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    if settings.night_light_enabled:
        red, green, blue = kelvin_to_rgb(settings.night_light_temperature)
        strength = max(0.0, min(1.0, settings.night_light_strength / 100.0))
        alpha = 0.50 * strength
        layer = _over(layer, (red, green, blue, alpha))

    if circadian_temperature is not None:
        red, green, blue = kelvin_to_rgb(circadian_temperature)
        layer = _over(layer, (red, green, blue, 0.45))

    if settings.low_blue_light_enabled:
        level = max(0.0, min(1.0, settings.low_blue_light_level / 100.0))
        layer = _over(layer, (1.0, 0.82, 0.55, 0.40 * level))

    if settings.warm_tint_enabled:
        strength = max(0.0, min(1.0, settings.warm_tint_strength / 100.0))
        layer = _over(layer, (1.0, 0.90, 0.72, 0.30 * strength))

    if settings.software_dimming_enabled:
        level = max(5, min(100, settings.software_dimming_level))
        alpha = (1.0 - level / 100.0) * 0.85
        if alpha > 0:
            layer = _over(layer, (0.0, 0.0, 0.0, alpha))

    if layer[3] < 0.01:
        return None
    return layer


def overlay_rgba_string(settings: EffectSettings,
                        circadian_temperature: float | None = None) -> str:
    """Same as :func:`overlay_color` but as a QML ``#AARRGGBB`` string."""
    spec = overlay_color(settings, circadian_temperature)
    if spec is None:
        return "#00000000"
    red, green, blue, alpha = spec
    return "#{:02X}{:02X}{:02X}{:02X}".format(
        round(max(0.0, min(1.0, alpha)) * 255),
        round(max(0.0, min(1.0, red)) * 255),
        round(max(0.0, min(1.0, green)) * 255),
        round(max(0.0, min(1.0, blue)) * 255),
    )


def transform_for(settings: EffectSettings) -> ColorTransform:
    """Combine every enabled effect into a single transform."""
    transform = ColorTransform()
    if settings.night_light_enabled:
        transform = transform.combine(
            night_light_transform(settings.night_light_temperature,
                                  settings.night_light_strength))
    if settings.low_blue_light_enabled:
        transform = transform.combine(
            low_blue_light_transform(settings.low_blue_light_level))
    if settings.software_dimming_enabled:
        transform = transform.combine(
            software_dimming_transform(settings.software_dimming_level))
    if settings.warm_tint_enabled:
        transform = transform.combine(warm_tint_transform(settings.warm_tint_strength))
    if settings.cleartype_enabled:
        transform = transform.combine(cleartype_transform())
    return transform


def hyprsunset_params(settings: EffectSettings,
                      circadian_temperature: float | None = None
                      ) -> tuple[float, int]:
    """Map the enabled effects to ``(temperature_K, gamma_percent)``.

    ``hyprsunset`` applies ``gamma * blackbody(temperature)`` to every output.
    Temperature is the coldest (lowest) value any enabled effect asks for, and
    the gamma percent is the software-dimming level (100 = no dimming).
    """
    temperature = 6500.0

    if settings.night_light_enabled:
        strength = max(0.0, min(1.0, settings.night_light_strength / 100.0))
        target = float(settings.night_light_temperature)
        temperature = min(temperature, 6500.0 - (6500.0 - target) * strength)

    if circadian_temperature is not None:
        temperature = min(temperature, float(circadian_temperature))

    if settings.low_blue_light_enabled:
        level = max(0.0, min(1.0, settings.low_blue_light_level / 100.0))
        temperature = min(temperature, 6500.0 - 3500.0 * level)

    if settings.warm_tint_enabled:
        strength = max(0.0, min(1.0, settings.warm_tint_strength / 100.0))
        temperature = min(temperature, 6500.0 - 1500.0 * strength)

    dim = settings.software_dimming_level if settings.software_dimming_enabled else 100
    return max(1000.0, temperature), max(5, min(100, int(dim)))


class DisplayEffects:
    """Owns the colour-control backend and applies the configured effects."""

    def __init__(self, settings: EffectSettings | None = None) -> None:
        self._controller = make_controller()
        self._settings = settings or EffectSettings()
        self._circadian_temperature: float | None = None
        self._active = False

    @property
    def available(self) -> bool:
        return bool(getattr(self._controller, "available", False))

    @property
    def controller_name(self) -> str:
        return getattr(self._controller, "name", "none")

    @property
    def error(self) -> str:
        return getattr(self._controller, "error", "")

    @property
    def active(self) -> bool:
        return self._active

    def update_settings(self, settings: EffectSettings,
                        circadian_temperature: float | None = None) -> None:
        self._settings = settings
        self._circadian_temperature = circadian_temperature

    def apply(self) -> bool:
        """Recompute and push the combined effect to the backend."""
        transform = transform_for(self._settings)
        if self._circadian_temperature is not None:
            transform = transform.combine(
                night_light_transform(self._circadian_temperature, 100))
        temperature, dim = hyprsunset_params(self._settings,
                                             self._circadian_temperature)
        self._active = self._controller.apply(transform, temperature, dim)
        return self._active

    def reset(self) -> bool:
        self._active = False
        return self._controller.reset()

    def close(self) -> None:
        if self._active:
            self.reset()
        self._controller.close()
