"""Circadian colour temperature.

The Windows build's "Circadian mode" is a schedule that warms the panel in the
evening and returns it to neutral in the morning.  This module computes the
target colour temperature for any moment, either from a fixed sunrise/sunset
pair or from geographic coordinates using an approximate solar model.

The controller is pure (it takes an explicit ``datetime``); the core layer calls
it once a minute and routes the result through
:class:`~eyecareu.display.effects.DisplayEffects`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta


def parse_hhmm(text: str, fallback: time) -> time:
    try:
        hours, minutes = text.strip().split(":")
        return time(int(hours) % 24, int(minutes) % 60)
    except (ValueError, AttributeError):
        return fallback


def solar_times(day: date, latitude: float, longitude: float,
                zenith: float = 90.833) -> tuple[datetime, datetime]:
    """Approximate sunrise/sunset (NOAA algorithm), in local naive time.

    Accurate to a couple of minutes, which is ample for a gradual colour shift.
    """
    n = day.toordinal() - date(2000, 1, 1).toordinal() + 1
    lng_hour = longitude / 15.0
    t = n + (6 - lng_hour) / 24.0
    mean_anomaly = (0.9856 * t) - 3.289
    true_long = (mean_anomaly + 1.916 * math.sin(math.radians(mean_anomaly))
                 + 0.020 * math.sin(math.radians(2 * mean_anomaly)) + 282.634) % 360
    right_asc = math.degrees(math.atan(0.91764 * math.tan(math.radians(true_long)))) % 360
    l_quadrant = (math.floor(true_long / 90)) * 90
    ra_quadrant = (math.floor(right_asc / 90)) * 90
    right_asc = (right_asc + (l_quadrant - ra_quadrant)) / 15.0
    sin_dec = 0.39782 * math.sin(math.radians(true_long))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_hour = ((math.cos(math.radians(zenith)) - (sin_dec * math.sin(math.radians(latitude))))
                / (cos_dec * math.cos(math.radians(latitude))))
    cos_hour = max(-1.0, min(1.0, cos_hour))

    def _local(hours_utc: float) -> datetime:
        # Convert UTC hours to naive local time using the standard-time offset.
        offset = round(longitude / 15.0)
        total = hours_utc + offset
        total %= 24
        return datetime.combine(day, time(int(total), int((total % 1) * 60)))

    sunrise = _local((360 - math.degrees(math.acos(cos_hour))) / 15.0)
    sunset = _local(math.degrees(math.acos(cos_hour)) / 15.0)
    return sunrise, sunset


@dataclass(slots=True)
class CircadianState:
    temperature: float
    phase: str            # "day" | "night" | "sunrise" | "sunset"
    sunrise: time
    sunset: time


class CircadianController:
    """Turns settings + current time into a colour temperature."""

    def __init__(self, settings) -> None:
        self.settings = settings

    def update_settings(self, settings) -> None:
        self.settings = settings

    def _window(self, when: datetime) -> tuple[time, time]:
        settings = self.settings
        if settings.use_location and settings.latitude is not None and settings.longitude is not None:
            sunrise_dt, sunset_dt = solar_times(when.date(), settings.latitude, settings.longitude)
            return sunrise_dt.time(), sunset_dt.time()
        return (parse_hhmm(settings.sunrise, time(7, 0)),
                parse_hhmm(settings.sunset, time(19, 0)))

    def state_at(self, when: datetime) -> CircadianState:
        settings = self.settings
        sunrise, sunset = self._window(when)
        moment = when.time()

        def minutes(value: time) -> float:
            return value.hour * 60 + value.minute

        now_min = minutes(moment)
        rise_min = minutes(sunrise)
        set_min = minutes(sunset)
        transition = max(1, settings.transition_minutes)

        day_temp = float(settings.day_temperature)
        night_temp = float(settings.night_temperature)

        if rise_min <= now_min <= set_min:
            # Daytime: ramp back to the day temperature after sunrise.
            since_rise = now_min - rise_min
            if since_rise < transition:
                ratio = since_rise / transition
                temp = night_temp + (day_temp - night_temp) * ratio
                return CircadianState(temp, "sunrise", sunrise, sunset)
            before_set = set_min - now_min
            if before_set < transition:
                ratio = before_set / transition
                temp = night_temp + (day_temp - night_temp) * ratio
                return CircadianState(temp, "sunset", sunrise, sunset)
            return CircadianState(day_temp, "day", sunrise, sunset)

        # Night: fully warm.
        return CircadianState(night_temp, "night", sunrise, sunset)

    def temperature_at(self, when: datetime) -> float:
        return self.state_at(when).temperature

    def next_change(self, when: datetime) -> timedelta:
        """Time until the temperature next changes by a noticeable amount."""
        sunrise, sunset = self._window(when)
        candidates = [datetime.combine(when.date(), sunrise),
                      datetime.combine(when.date(), sunset)]
        for candidate in candidates:
            if candidate > when:
                return candidate - when
        return timedelta(minutes=60)
