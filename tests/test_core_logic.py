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

    def test_color_mode_names(self) -> None:
        self.assertEqual(mccs.color_mode_name(0x00), "Standard")
        self.assertEqual(mccs.color_mode_name(0x28), "Game")
        self.assertEqual(mccs.color_mode_name(0x0F), "M-book")
        self.assertEqual(mccs.color_mode_name(0x12), "User")
        self.assertEqual(mccs.color_mode_name(0x1F), "ePaper")
        # Cinema is 0x32, not the plain 0x03 some panels advertise.
        self.assertEqual(mccs.color_mode_name(0x32), "Cinema")
        # The GW-series "SHCode" variants share the low byte 0x27.
        self.assertEqual(mccs.color_mode_name(0x0127), "Care Mode")
        self.assertEqual(mccs.color_mode_name(0x0227), "Coding")
        self.assertEqual(mccs.color_mode_name(0x0427), "ePaper")
        # Unknown values degrade to a readable, non-crashing label.
        self.assertEqual(mccs.color_mode_name(0xAB), "Mode 0xAB")
        self.assertEqual(mccs.color_mode_name(0x0ABC), "Mode 0x0ABC")

    def test_expand_color_mode(self) -> None:
        # A plain code expands to itself...
        self.assertEqual(mccs.expand_color_mode(0x28), (0x0028,))
        # ...while an SHCode code fans out to every real mode.
        self.assertEqual(mccs.expand_color_mode(0x27), (0x0127, 0x0227, 0x0427))


class CapabilityStringTests(unittest.TestCase):
    """Parsing of a real BenQ capability string (GW2490, MCCS 2.2)."""

    CAPS = (
        "(prot(monitor)type(lcd)model(GW2490)cmds(01 02 03 07 0C E3 F3)"
        "vcp(02 04 08 10 12 14(04 05 08 0B) 16 18 19 1A 52 60(0F 11 12) "
        "62 72(50 64 78 8C A0) 86 (02 05) 87 8D (01 02) C1 C2 C8 C9 D2 "
        "DC(00 03 0F 12 27 28) DF E1 E2(00 FF) EA(00 01 02 03 04 05) "
        "EB(00 01 02 03) EE (00 01 02) F0 (00 01 02) F1(00 1E 2D 3D) "
        "F8 (00 0A 14 1E) FD(00 01 02 03 04) FE FF)mswhql(1)mccs_ver(2.2))"
    )

    def test_vcp_block_is_paren_balanced(self) -> None:
        from eyecareu.ddc.manager import _supported_vcps

        codes = _supported_vcps(self.CAPS)
        # Top-level codes that a naive regex would drop after the first ')'.
        self.assertIn(0x62, codes)   # volume
        self.assertIn(0xDC, codes)   # picture mode
        self.assertIn(0x72, codes)
        # Nested value-list tokens are not VCP codes.
        self.assertNotIn(0x50, codes)
        self.assertNotIn(0x05, codes)
        self.assertNotIn(0x0B, codes)

    def test_advertised_color_modes(self) -> None:
        from eyecareu.ddc.manager import _supported_color_modes

        # The SHCode code 0x27 fans out to its three real modes, in place.
        self.assertEqual(_supported_color_modes(self.CAPS),
                         [0x0000, 0x0003, 0x000F, 0x0012,
                          0x0127, 0x0227, 0x0427, 0x0028])

    def test_no_color_modes_without_dc(self) -> None:
        from eyecareu.ddc.manager import _supported_color_modes

        self.assertEqual(_supported_color_modes("(prot(monitor)vcp(10 62))"), [])


class ProbeAndPollTests(unittest.TestCase):
    """Probing is cached; polling is a cheap value-only refresh.

    These cover the fix for the UI lag: the capability string must be read once
    (then cached in memory and on disk) instead of on every poll, and a monitor
    with no DDC link must not be re-probed on the bus.
    """

    CAPS = CapabilityStringTests.CAPS

    #: The verified picture-mode values for the GW2490 (model-specific override).
    GW_MODES = [0x0000, 0x0032, 0x0028, 0x0427, 0x0127, 0x0227, 0x000F, 0x0012]
    #: Codes the capability string advertises, expanded to full values.
    CAPS_MODES = [0x0000, 0x0003, 0x000F, 0x0012,
                  0x0127, 0x0227, 0x0427, 0x0028]

    class FakeBackend:
        name = "fake"

        def __init__(self, caps: str = "", link_ok: bool = True,
                     link_error: str = "") -> None:
            self.caps = caps
            self.link_ok = link_ok
            self.link_error = link_error
            self.caps_reads = 0
            self.vcp_reads = 0

        def get_vcp(self, monitor, vcp):
            from eyecareu.ddc.base import VcpValue

            self.vcp_reads += 1
            if vcp == 0xDF:                       # VCP_VERSION link test
                return VcpValue(vcp=vcp, supported=self.link_ok,
                                error="" if self.link_ok else self.link_error,
                                current=0x12, maximum=0x12)
            return VcpValue(vcp=vcp, current=40, maximum=100, supported=True)

        def set_vcp(self, monitor, vcp, value) -> bool:
            return True

        def get_vcp_settled(self, monitor, vcp):
            return self.get_vcp(monitor, vcp)

        def set_vcp_ack(self, monitor, vcp, value):
            self.set_vcp(monitor, vcp, value)
            return None                  # panel does not acknowledge writes

        def get_capabilities(self, monitor) -> str:
            self.caps_reads += 1
            return self.caps

        def close(self) -> None:
            pass

    def _identity(self, model: str = "GW2490"):
        from eyecareu.ddc.base import MonitorIdentity

        return MonitorIdentity(display_id="card1-HDMI-A-1", i2c_bus=4,
                               manufacturer="BNQ", model=model)

    def _refresh(self, manager, identity):
        from unittest import mock

        with mock.patch("eyecareu.ddc.manager.discover_monitors",
                        return_value=[identity]):
            return manager.refresh()

    def test_capabilities_read_once_in_memory(self) -> None:
        from unittest import mock

        from eyecareu.ddc.manager import MonitorManager

        backend = self.FakeBackend(caps=self.CAPS)
        manager = MonitorManager(backend=backend)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("eyecareu.ddc.capcache.state_dir",
                           return_value=Path(tmp)):
            identity = self._identity()
            first = self._refresh(manager, identity)
            second = self._refresh(manager, identity)
            manager.poll()
            manager.poll()
        self.assertEqual(backend.caps_reads, 1)
        self.assertEqual(first[0].color_modes, self.GW_MODES)
        self.assertEqual(second[0].color_modes, first[0].color_modes)

    def test_capabilities_cached_on_disk(self) -> None:
        from unittest import mock

        from eyecareu.ddc.manager import MonitorManager

        identity = self._identity()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("eyecareu.ddc.capcache.state_dir",
                           return_value=Path(tmp)):
            cold = self.FakeBackend(caps=self.CAPS)
            self._refresh(MonitorManager(backend=cold), identity)
            warm = self.FakeBackend(caps=self.CAPS)
            states = self._refresh(MonitorManager(backend=warm), identity)
        self.assertEqual(cold.caps_reads, 1)
        self.assertEqual(warm.caps_reads, 0)      # served from disk
        self.assertEqual(states[0].color_modes, self.GW_MODES)

    def test_poll_only_reads_live_values(self) -> None:
        from unittest import mock

        from eyecareu.ddc.manager import MonitorManager

        backend = self.FakeBackend(caps=self.CAPS)
        manager = MonitorManager(backend=backend)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("eyecareu.ddc.capcache.state_dir",
                           return_value=Path(tmp)):
            self._refresh(manager, self._identity())
            backend.vcp_reads = 0
            manager.poll()
        # A poll reads brightness + colour mode only (not volume/mute/firmware),
        # and never the capability string.
        self.assertEqual(backend.vcp_reads, 2)
        self.assertEqual(backend.caps_reads, 1)

    def test_offline_monitor_skips_capability_read(self) -> None:
        from unittest import mock

        from eyecareu.ddc.manager import MonitorManager

        backend = self.FakeBackend(
            link_ok=False, link_error="DDC transaction failed: I/O error")
        manager = MonitorManager(backend=backend)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("eyecareu.ddc.capcache.state_dir",
                           return_value=Path(tmp)):
            states = self._refresh(manager, self._identity())
        self.assertFalse(states[0].online)
        self.assertEqual(backend.caps_reads, 0)

    def test_progress_callback_fires_before_value_reads(self) -> None:
        from unittest import mock

        from eyecareu.ddc.manager import MonitorManager

        backend = self.FakeBackend(caps=self.CAPS)
        manager = MonitorManager(backend=backend)
        seen: list[tuple[int, list[int]]] = []
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("eyecareu.ddc.capcache.state_dir",
                           return_value=Path(tmp)), \
                mock.patch("eyecareu.ddc.manager.discover_monitors",
                           return_value=[self._identity()]):
            manager.refresh(on_update=lambda: seen.append(
                (backend.caps_reads,
                 list(manager.monitor("card1-HDMI-A-1").color_modes))))
        # A progress callback fires before the slow capability read, and the
        # verified per-model mode list is already published by then, so the
        # Display page is usable without waiting for the capability string.
        early = [modes for reads, modes in seen if reads == 0]
        self.assertTrue(early)
        # Cinema comes from the GW2490 table, not from the capability string.
        self.assertTrue(any(0x0032 in modes for modes in early))

    def test_offline_monitor_recovers_on_later_poll(self) -> None:
        from unittest import mock

        from eyecareu.ddc.manager import MonitorManager

        backend = self.FakeBackend(
            link_ok=False, link_error="DDC transaction failed: I/O error")
        manager = MonitorManager(backend=backend)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("eyecareu.ddc.capcache.state_dir",
                           return_value=Path(tmp)):
            identity = self._identity()
            states = self._refresh(manager, identity)
            self.assertFalse(states[0].online)
            self.assertEqual(backend.caps_reads, 0)
            # A transient bus failure must not mark the monitor offline for the
            # rest of the session: the link test is retried on later polls.
            backend.link_ok = True
            backend.caps = self.CAPS
            states[0].retry_after = 0.0
            manager.poll()
        state = manager.monitor(identity.display_id)
        self.assertTrue(state.online)
        self.assertEqual(backend.caps_reads, 1)
        self.assertEqual(state.color_modes, self.GW_MODES)

    def test_failed_read_keeps_last_good_value(self) -> None:
        from unittest import mock

        from eyecareu.ddc.base import VcpValue
        from eyecareu.ddc.manager import MonitorManager

        backend = self.FakeBackend(caps=self.CAPS)
        manager = MonitorManager(backend=backend)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("eyecareu.ddc.capcache.state_dir",
                           return_value=Path(tmp)):
            identity = self._identity()
            states = self._refresh(manager, identity)
            self.assertTrue(states[0].brightness.supported)
            good = states[0].brightness.current
            original = backend.get_vcp
            backend.get_vcp = lambda monitor, vcp: (       # next read fails
                VcpValue(vcp=vcp) if vcp == 0x10 else original(monitor, vcp))
            manager.poll()
        self.assertTrue(states[0].brightness.supported)
        self.assertEqual(states[0].brightness.current, good)

    def test_failed_capability_read_is_retried(self) -> None:
        from unittest import mock

        from eyecareu.ddc.manager import MonitorManager

        backend = self.FakeBackend(caps="")        # flaky read returns nothing
        manager = MonitorManager(backend=backend)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("eyecareu.ddc.capcache.state_dir",
                           return_value=Path(tmp)):
            state = self._refresh(manager, self._identity(model="Unknown-Model"))[0]
            self.assertTrue(state.online)
            self.assertEqual(state.color_modes, list(mccs.DEFAULT_COLOR_MODES))
            # The read is retried on a later poll and the real modes appear.
            backend.caps = self.CAPS
            state.retry_after = 0.0
            manager.poll()
        self.assertEqual(state.color_modes, self.CAPS_MODES)

    def test_capability_retries_are_bounded(self) -> None:
        from unittest import mock

        from eyecareu.ddc.manager import (
            CAPABILITY_ATTEMPTS,
            NO_RETRY,
            MonitorManager,
        )

        backend = self.FakeBackend(caps="")
        manager = MonitorManager(backend=backend)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("eyecareu.ddc.capcache.state_dir",
                           return_value=Path(tmp)):
            state = self._refresh(manager, self._identity())[0]
            for _ in range(CAPABILITY_ATTEMPTS - 1):
                state.retry_after = 0.0
                manager.poll()
            self.assertEqual(state.caps_attempts, CAPABILITY_ATTEMPTS)
            self.assertEqual(state.retry_after, NO_RETRY)
            reads = backend.caps_reads
            manager.poll()                          # bounded: no further read
            self.assertEqual(backend.caps_reads, reads)


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


class I2cReplyTests(unittest.TestCase):
    """A stale frame left in the adapter's FIFO must be skipped, not returned.

    The adapter routinely still holds the previous frame (often a capability
    chunk) when the reply to the current request is read.
    """

    def test_stale_frame_is_skipped(self) -> None:
        from unittest import mock

        from eyecareu.ddc.i2c import I2cDdcBackend

        backend = I2cDdcBackend(retries=1)
        stale = bytes([0x6E, 0x84, 0xE3, 0x00, 0x1A, 0x00])          # 0xE3 chunk
        valid = bytes([0x6E, 0x88, 0x02, 0x00, 0xDC, 0x00, 0x04, 0x28, 0x00, 0x32])
        frames = iter([stale, valid])
        with mock.patch("eyecareu.ddc.i2c.os.set_blocking"), \
                mock.patch("eyecareu.ddc.i2c.os.read",
                           side_effect=lambda fd, n: next(frames)):
            data = backend._read_reply(
                99, 8,
                lambda r: len(r) >= 3 and r[0] == 0x02 and r[2] == 0xDC)
        self.assertEqual(data[2], 0xDC)
        self.assertEqual((data[6] << 8) | data[7], 0x0032)

    def test_rotated_window_is_rescanned(self) -> None:
        # The adapter hands back a circular window: the frame can begin at any
        # offset, and one that crosses the end wraps around to the front.
        from eyecareu.ddc.i2c import I2cDdcBackend

        # 0xDC = 0x0032 (Cinema).  Display frames checksum to 0x50.
        frame = bytes([0x6E, 0x88, 0x02, 0x00, 0xDC, 0x00, 0x04, 0x28,
                       0x00, 0x32, 0x76])
        window = bytearray(b"\x00" * 32)
        window[27:32] = frame[:5]        # tail of the frame ...
        window[0:6] = frame[5:]          # ... wrapping to the front

        data = I2cDdcBackend._scan_frame(
            bytes(window), 8,
            lambda r: len(r) >= 3 and r[0] == 0x02 and r[2] == 0xDC)
        self.assertIsNotNone(data)
        self.assertEqual((data[6] << 8) | data[7], 0x0032)

    def test_stale_frame_for_another_vcp_is_ignored(self) -> None:
        from eyecareu.ddc.i2c import I2cDdcBackend

        # A leftover brightness reply must not satisfy a picture-mode request.
        stale = bytes([0x6E, 0x88, 0x02, 0x00, 0x10, 0x00, 0x00, 0x64,
                       0x00, 0x62, 0xA2])
        data = I2cDdcBackend._scan_frame(
            stale + b"\x00" * (32 - len(stale)), 8,
            lambda r: len(r) >= 3 and r[0] == 0x02 and r[2] == 0xDC)
        self.assertIsNone(data)

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


class ColorModeWriteTests(unittest.TestCase):
    """``set_color_mode`` writes full values and confirms via a retried read."""

    class FakeBackend:
        name = "fake"

        def __init__(self, accepts: set[int], stale_first: bool = False,
                     acks: bool = False, defer_writes: bool = False,
                     clamp_to: int | None = None) -> None:
            self.accepts = set(accepts)
            self.writes: list[int] = []
            self.current = 0x0000
            self.stale_first = stale_first
            self.acks = acks
            self.defer_writes = defer_writes
            self.clamp_to = clamp_to
            self._deferred = False
            self._just_deferred = False
            self._stale: int | None = None

        def get_vcp(self, monitor, vcp):
            from eyecareu.ddc.base import VcpValue

            current = self.current
            if self._stale is not None:        # first read after a write lags
                current = self._stale
                self._stale = None
            return VcpValue(vcp=vcp, current=current, maximum=0x0428,
                            supported=True)

        def get_vcp_settled(self, monitor, vcp):
            return self.get_vcp(monitor, vcp)

        def set_vcp(self, monitor, vcp, value) -> bool:
            self.writes.append(value)
            if self.stale_first and self._stale is None:
                self._stale = self.current           # echo the *old* mode once
            self._just_deferred = False
            if self.defer_writes and not self._deferred:
                # The adapter is still replaying the previous answer.
                self._deferred = True
                self._just_deferred = True
                return True
            if value in self.accepts:
                self.current = value
            elif self.clamp_to is not None:
                self.current = self.clamp_to
            return True

        def set_vcp_ack(self, monitor, vcp, value):
            """Mirror a real panel: None = silent, else the applied mode."""
            self.set_vcp(monitor, vcp, value)
            if not self.acks:
                return None
            if self._just_deferred:
                return self.current          # replayed: still the old mode
            return value if value in self.accepts else self.current

        def get_capabilities(self, monitor) -> str:
            return ""

        def close(self) -> None:
            pass

    def setUp(self) -> None:
        from unittest import mock

        delay = mock.patch("eyecareu.ddc.manager.COLOR_MODE_CONFIRM_DELAY_S", 0)
        delay.start()
        self.addCleanup(delay.stop)

    def _manager(self, accepts, stale_first: bool = False, acks: bool = False,
                 defer_writes: bool = False, clamp_to: int | None = None):
        from eyecareu.ddc.base import MonitorIdentity
        from eyecareu.ddc.manager import MonitorManager, MonitorState

        backend = self.FakeBackend(accepts, stale_first=stale_first,
                                   acks=acks, defer_writes=defer_writes,
                                   clamp_to=clamp_to)
        manager = MonitorManager(backend=backend)
        identity = MonitorIdentity(display_id="d0", i2c_bus=4, manufacturer="BNQ")
        manager._monitors["d0"] = MonitorState(identity=identity)
        return manager, backend

    def test_full_value_written_verbatim(self) -> None:
        # Cinema on a GW-series panel is 0x32 — stored as-is, not 0x03.
        manager, backend = self._manager({0x0032})
        self.assertTrue(manager.set_color_mode("d0", 0x0032))
        self.assertEqual(backend.writes, [0x0032])
        self.assertEqual(backend.current, 0x0032)

    def test_shcode_mode_written_verbatim(self) -> None:
        # A full SHCode value (0x0227 = Coding) must not be re-laddered into a
        # *different* mode the way the old low-byte matching did.
        manager, backend = self._manager({0x0227})
        self.assertTrue(manager.set_color_mode("d0", 0x0227))
        self.assertEqual(backend.writes, [0x0227])
        self.assertEqual(backend.current, 0x0227)

    def test_bare_code_expands_to_full_values(self) -> None:
        manager, backend = self._manager({0x0227})
        self.assertTrue(manager.set_color_mode("d0", 0x27))
        self.assertEqual(backend.writes, [0x0127, 0x0227])

    def test_unknown_code_tries_shcode_ladder(self) -> None:
        manager, backend = self._manager({0x0105})
        self.assertTrue(manager.set_color_mode("d0", 0x05))
        self.assertEqual(backend.writes, [0x0005, 0x0105])

    def test_rejected_mode_returns_false(self) -> None:
        manager, backend = self._manager(set())
        self.assertFalse(manager.set_color_mode("d0", 0x0003))
        self.assertEqual(backend.writes, [0x0003, 0x0103, 0x0203, 0x0403])

    def test_stale_first_read_is_retried(self) -> None:
        # The first read-back after a write often returns the *old* mode; the
        # write must still be reported as successful.
        manager, backend = self._manager({0x0032}, stale_first=True)
        self.assertTrue(manager.set_color_mode("d0", 0x0032))
        self.assertEqual(backend.current, 0x0032)

    def test_known_low_byte_mode_is_not_laddered(self) -> None:
        # 0x28 (Game) is a complete value, not a bare advertised code, so it
        # must be written once instead of being tried as 0x0128/0x0228/0x0428.
        manager, backend = self._manager({0x0028})
        self.assertTrue(manager.set_color_mode("d0", 0x0028))
        self.assertEqual(backend.writes, [0x0028])

    def test_acknowledged_write_skips_read_back(self) -> None:
        manager, backend = self._manager({0x0032}, acks=True)
        self.assertTrue(manager.set_color_mode("d0", 0x0032))
        self.assertEqual(backend.writes, [0x0032])

    def test_acknowledged_clamp_is_reported_as_failure(self) -> None:
        # A BenQ panel answers result 0x00 even for a mode it does not support
        # but echoes the value it fell back to; that is not success.
        manager, backend = self._manager({0x0032}, acks=True)
        self.assertFalse(manager.set_color_mode("d0", 0x0003))
        self.assertEqual(backend.writes, [0x0003, 0x0103, 0x0203, 0x0403])

    def test_replayed_acknowledgement_is_written_again(self) -> None:
        # The adapter can answer a write with the *previous* mode — and then
        # keep replaying it for the read-back too.  Rather than reporting a
        # failure the write is issued once more.
        manager, backend = self._manager({0x0032}, acks=True, defer_writes=True)
        self.assertTrue(manager.set_color_mode("d0", 0x0032))
        self.assertEqual(backend.writes, [0x0032, 0x0032])
        self.assertEqual(backend.current, 0x0032)

    def test_clamped_single_value_is_not_rewritten(self) -> None:
        # A genuine clamp to a *different* mode is not retried.
        manager, backend = self._manager(set(), acks=True, clamp_to=0x0012)
        self.assertFalse(manager.set_color_mode("d0", 0x0032))
        self.assertEqual(backend.writes, [0x0032])


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
