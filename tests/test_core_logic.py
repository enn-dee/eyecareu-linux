"""Unit tests for the pure-logic layers (no Qt, no hardware)."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from eyecareu.config import Config
from eyecareu.ddc.edid import parse_edid, manufacturer_name
from eyecareu.display.gamma import ColorTransform, kelvin_to_rgb
from eyecareu.features.circadian import CircadianController
from eyecareu.features.reminders import (
    ConditionReminder,
    IntervalReminder,
    ReminderContext,
)
from eyecareu.features.report import ScreenTimeTracker
from eyecareu.features.timers import PhaseTimer, make_pomodoro, make_twenty
from eyecareu import mccs


class ConfigTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            cfg = Config()
            cfg.effects.night_light_temperature = 4200
            cfg.timers.pomodoro_work_minutes = 40
            cfg.reminders.break_interval_minutes = 45
            cfg.save(path)

            loaded = Config.load(path)
            self.assertEqual(loaded.effects.night_light_temperature, 4200)
            self.assertEqual(loaded.timers.pomodoro_work_minutes, 40)
            self.assertEqual(loaded.reminders.break_interval_minutes, 45)

    def test_unknown_keys_preserved_and_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text('{"version": 1, "general": {"language": "de", "zzz": 1}}')
            loaded = Config.load(path)
            self.assertEqual(loaded.general.language, "de")

    def test_missing_file_returns_defaults(self) -> None:
        loaded = Config.load(Path("/nonexistent/does/not/exist.json"))
        self.assertEqual(loaded.version, 1)


class EdidTests(unittest.TestCase):
    @staticmethod
    def _edid(manufacturer: bytes, name: str) -> bytes:
        data = bytearray(128)
        data[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
        data[8:10] = manufacturer
        data[10:12] = (0x1234).to_bytes(2, "little")
        data[16] = 30          # week
        data[17] = 33          # year -> 2023
        data[21] = 53          # width cm -> 530 mm
        data[22] = 30          # height cm
        block = bytearray(18)
        block[3] = 0xFC
        encoded = name.encode("ascii")[:13].ljust(13, b" ")
        block[5:18] = encoded
        data[54:72] = block
        return bytes(data)

    def test_parse(self) -> None:
        parsed = parse_edid(self._edid(b"\x09\xd1", "GW2490"))
        self.assertTrue(parsed["valid"])
        self.assertEqual(parsed["manufacturer"], "BNQ")
        self.assertEqual(parsed["model"], "GW2490")
        self.assertEqual(parsed["year"], 2023)
        self.assertEqual(parsed["width_mm"], 530)

    def test_invalid(self) -> None:
        self.assertFalse(parse_edid(b"short")["valid"])

    def test_vendor_lookup(self) -> None:
        self.assertEqual(manufacturer_name("bnq"), "BenQ")


class GammaTests(unittest.TestCase):
    def test_kelvin_monotonic(self) -> None:
        warm = kelvin_to_rgb(3000)
        neutral = kelvin_to_rgb(6500)
        # Warmer (lower K) light has relatively less blue.
        self.assertLess(warm[2], neutral[2] + 1e-6)
        self.assertAlmostEqual(max(neutral), 1.0, places=5)

    def test_identity_ramp(self) -> None:
        self.assertTrue(ColorTransform().is_identity())

    def test_ramp_bounds(self) -> None:
        red, green, blue = ColorTransform(blue=0.5, brightness=0.5).build_ramps(8)
        self.assertEqual(len(red), 8)
        self.assertTrue(all(0 <= v <= 65535 for v in red + green + blue))
        self.assertLess(max(blue), max(red))


class TimerTests(unittest.TestCase):
    def test_twenty_cycle(self) -> None:
        timer = PhaseTimer("twenty", work_seconds=10, break_seconds=5)
        state = timer.start(now=0)
        self.assertEqual(state.phase, "work")
        self.assertIsNone(timer.tick(5))
        state = timer.tick(10)
        self.assertEqual(state.phase, "break")
        self.assertEqual(state.cycles, 1)
        state = timer.tick(15)
        self.assertEqual(state.phase, "work")
        self.assertEqual(state.cycles, 1)

    def test_pause_resume(self) -> None:
        timer = PhaseTimer("t", work_seconds=10, break_seconds=5)
        timer.start(0)
        timer.pause(4)
        self.assertIsNone(timer.tick(8))
        self.assertEqual(timer.remaining(8), 6)
        timer.resume(8)
        self.assertIsNone(timer.tick(13))
        self.assertEqual(timer.tick(14).phase, "break")

    def test_skip(self) -> None:
        timer = PhaseTimer("t", work_seconds=10, break_seconds=5)
        timer.start(0)
        state = timer.skip(1)
        self.assertEqual(state.phase, "break")

    def test_pomodoro_long_break(self) -> None:
        timer = PhaseTimer("pomodoro", work_seconds=10, break_seconds=5,
                           long_break_seconds=20, cycles_before_long=2)
        timer.start(0)
        timer.tick(10)              # work 1 -> short break
        timer.tick(15)              # -> work 2
        state = timer.tick(25)      # work 2 -> long break
        self.assertEqual(state.phase, "long_break")
        self.assertEqual(state.cycles, 2)

    def test_factories_from_settings(self) -> None:
        cfg = Config()
        cfg.timers.twenty_work_minutes = 25
        timer = make_twenty(cfg.timers)
        timer.start(0)
        self.assertAlmostEqual(timer.remaining(0), 25 * 60)
        pomo = make_pomodoro(cfg.timers)
        self.assertEqual(pomo.kind, "pomodoro")


class ReminderTests(unittest.TestCase):
    def test_interval(self) -> None:
        reminder = IntervalReminder("break", 60, "t", "m", enabled=True)
        self.assertIsNone(reminder.tick(ReminderContext(now=0)))
        self.assertIsNone(reminder.tick(ReminderContext(now=59)))
        event = reminder.tick(ReminderContext(now=60))
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "break")

    def test_interval_ignores_inactive_screen(self) -> None:
        reminder = IntervalReminder("break", 60, "t", "m", enabled=True)
        reminder.arm(0)
        self.assertIsNone(reminder.tick(ReminderContext(now=120, screen_active=False)))

    def test_condition_hold(self) -> None:
        reminder = ConditionReminder("low_light", threshold=100, hold_seconds=30,
                                     title="t", message="m", enabled=True)
        self.assertIsNone(reminder.tick(ReminderContext(now=0, ambient_lux=50)))
        self.assertIsNone(reminder.tick(ReminderContext(now=20, ambient_lux=50)))
        event = reminder.tick(ReminderContext(now=31, ambient_lux=50))
        self.assertIsNotNone(event)
        # Recovers when light returns.
        self.assertIsNone(reminder.tick(ReminderContext(now=40, ambient_lux=200)))

    def test_snooze(self) -> None:
        reminder = IntervalReminder("break", 60, "t", "m", enabled=True)
        reminder.arm(0)
        reminder.snooze(now=0, minutes=10)
        self.assertIsNone(reminder.tick(ReminderContext(now=61)))
        self.assertIsNotNone(reminder.tick(ReminderContext(now=601)))


class CircadianTests(unittest.TestCase):
    def test_day_and_night(self) -> None:
        cfg = Config()
        cfg.circadian.day_temperature = 6500
        cfg.circadian.night_temperature = 3400
        cfg.circadian.sunrise = "07:00"
        cfg.circadian.sunset = "19:00"
        cfg.circadian.transition_minutes = 60
        controller = CircadianController(cfg.circadian)

        midday = controller.state_at(datetime(2026, 6, 1, 12, 0))
        self.assertEqual(midday.phase, "day")
        self.assertEqual(midday.temperature, 6500)

        midnight = controller.state_at(datetime(2026, 6, 1, 1, 0))
        self.assertEqual(midnight.phase, "night")
        self.assertEqual(midnight.temperature, 3400)

        sunrise = controller.state_at(datetime(2026, 6, 1, 7, 30))
        self.assertEqual(sunrise.phase, "sunrise")
        self.assertTrue(3400 < sunrise.temperature < 6500)


class ReportTests(unittest.TestCase):
    def test_accumulation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = ScreenTimeTracker(path=Path(tmp) / "st.json",
                                        daily_goal_minutes=100)
            now = 0.0
            tracker.tick(now, active=True)
            for _ in range(120):
                now += 1.0
                tracker.tick(now, active=True)
            self.assertGreaterEqual(tracker.today().total_minutes, 1)
            stats = tracker.stats()
            self.assertEqual(stats["goal_minutes"], 100)

    def test_break_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = ScreenTimeTracker(path=Path(tmp) / "st.json")
            now = 0.0
            tracker.tick(now, active=True)
            for _ in range(400):     # 400 s > _BREAK_MIN_SECONDS
                now += 1.0
                tracker.tick(now, active=True)
            tracker.tick(now + 100, active=False)   # triggers break close
            self.assertGreaterEqual(tracker.stats()["today_breaks"], 1)


class MccsTests(unittest.TestCase):
    def test_observed_codes(self) -> None:
        self.assertEqual(int(mccs.Vcp.BRIGHTNESS), 0x10)
        self.assertEqual(int(mccs.Vcp.VOLUME), 0x62)
        self.assertEqual(int(mccs.Vcp.MUTE), 0x8D)
        self.assertEqual(int(mccs.Vcp.COLOR_MODE), 0xDC)
        self.assertEqual(int(mccs.ColorMode.CARE_MODE), 0x01)


class HyprsunsetParamTests(unittest.TestCase):
    def _settings(self, **kwargs):
        from eyecareu.config import EffectSettings

        settings = EffectSettings()
        for key, value in kwargs.items():
            setattr(settings, key, value)
        return settings

    def test_neutral_when_nothing_enabled(self) -> None:
        from eyecareu.display.effects import hyprsunset_params

        temp, dim = hyprsunset_params(self._settings())
        self.assertEqual(temp, 6500.0)
        self.assertEqual(dim, 100)

    def test_night_light_temperature_and_strength(self) -> None:
        from eyecareu.display.effects import hyprsunset_params

        full = hyprsunset_params(self._settings(
            night_light_enabled=True, night_light_temperature=2700,
            night_light_strength=100))
        self.assertEqual(full[0], 2700.0)
        half = hyprsunset_params(self._settings(
            night_light_enabled=True, night_light_temperature=2700,
            night_light_strength=50))
        self.assertAlmostEqual(half[0], 4600.0)

    def test_dimming_and_circadian(self) -> None:
        from eyecareu.display.effects import hyprsunset_params

        temp, dim = hyprsunset_params(
            self._settings(software_dimming_enabled=True,
                           software_dimming_level=55),
            circadian_temperature=3400)
        self.assertEqual(dim, 55)
        self.assertEqual(temp, 3400.0)

    def test_never_warmer_than_neutral(self) -> None:
        from eyecareu.display.effects import hyprsunset_params

        temp, dim = hyprsunset_params(self._settings(
            low_blue_light_enabled=True, low_blue_light_level=100,
            warm_tint_enabled=True, warm_tint_strength=100))
        self.assertLess(temp, 6500.0)
        self.assertGreaterEqual(temp, 1000.0)
        self.assertEqual(dim, 100)


class I2cSetVcpTests(unittest.TestCase):
    """A ``Set VCP Feature`` must succeed even when the display stays silent."""

    def _call(self, read_effect) -> bool:
        from eyecareu.ddc.base import DdcError, MonitorIdentity
        from eyecareu.ddc.i2c import I2cDdcBackend
        from unittest import mock

        backend = I2cDdcBackend(retries=1)
        monitor = MonitorIdentity(display_id="test", i2c_bus=1)
        with mock.patch.object(backend, "_open_bus", return_value=99), \
                mock.patch.object(backend, "_write_packet"), \
                mock.patch.object(backend, "_read_reply", side_effect=read_effect), \
                mock.patch("eyecareu.ddc.i2c.os.close"):
            return backend.set_vcp(monitor, 0x10, 50)

    def test_silent_display_is_success(self) -> None:
        from eyecareu.ddc.base import DdcError

        self.assertTrue(self._call(DdcError("unexpected DDC source 0x00")))

    def test_positive_ack_is_success(self) -> None:
        self.assertTrue(self._call(lambda *a, **k: b"\x02\x00"))

    def test_negative_ack_is_failure(self) -> None:
        self.assertFalse(self._call(lambda *a, **k: b"\x02\x01"))

    def test_malformed_reply_is_success(self) -> None:
        # A reply that is not a Set VCP acknowledgement is ignored.
        self.assertTrue(self._call(lambda *a, **k: b"\x01\x00"))

    def test_permission_error_is_reported(self) -> None:
        from eyecareu.ddc.base import DdcError, MonitorIdentity
        from eyecareu.ddc.i2c import I2cDdcBackend
        from unittest import mock
        import errno as _errno

        backend = I2cDdcBackend(retries=1)
        monitor = MonitorIdentity(display_id="test", i2c_bus=1)
        with mock.patch.object(
                backend, "_open_bus",
                side_effect=OSError(_errno.EACCES, "denied")):
            with self.assertRaises(DdcError) as ctx:
                backend.set_vcp(monitor, 0x10, 50)
        self.assertIn("i2c", str(ctx.exception).lower())


class RegroupTests(unittest.TestCase):
    def test_pending_groups_detects_only_active_gaps(self) -> None:
        from types import SimpleNamespace
        from unittest import mock

        from eyecareu import regroup

        def fake_group(name):
            table = {
                "i2c": SimpleNamespace(gr_gid=1001, gr_mem=["alice"]),
                "video": SimpleNamespace(gr_gid=39, gr_mem=["bob"]),
            }
            if name in table:
                return table[name]
            raise KeyError(name)

        with mock.patch.object(regroup.os, "getgroups", return_value=[1000, 39]), \
                mock.patch.object(regroup.os, "getgid", return_value=1000), \
                mock.patch.object(regroup.pwd, "getpwuid") as pw, \
                mock.patch.object(regroup.grp, "getgrnam", side_effect=fake_group):
            pw.return_value = SimpleNamespace(pw_name="alice")
            # alice is in i2c but not active; video is active already.
            self.assertEqual(regroup._pending_groups(), ["i2c"])

    def test_reexec_disabled_by_marker(self) -> None:
        from unittest import mock

        from eyecareu import regroup

        with mock.patch.dict(regroup.os.environ, {regroup._MARKER: "1"}), \
                mock.patch.object(regroup, "_pending_groups",
                                  side_effect=AssertionError("should not run")):
            # Returns without inspecting groups.
            regroup.maybe_reexec(["eyecareu"])



if __name__ == "__main__":
    unittest.main()
