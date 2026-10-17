# Eye-CareU for Linux

A native Linux port of **BenQ Eye-CareU** (Windows v1.5.5.0), rebuilt for
Fedora and other modern distributions. It talks to BenQ and other DDC/CI
monitors over the standard Linux `i2c-dev` interface, and it reimplements the
Windows application's software eye-care features (timers, reminders, colour
temperature, screen-time report) as first-class Linux functionality.

* **Stack:** Python 3.10+ with PySide6 (Qt 6 / QML).
* **Sessions:** X11 and Wayland (see [Session support](#session-support)).
* **Dependencies:** `PySide6` plus optional `ddcutil`, `i2c-tools`, `xrandr`,
  `xprintidle` from the distribution.

---

## What was reverse engineered

Everything below was recovered from the shipped Windows installer
(`Eye-CareU for Win_V1.5.5.0_Windows_260811170539.zip`) by extracting the Inno
Setup payload and analysing the PE32+ binaries with REA plus `objdump` PE/PDB
parsing. Observed facts are separated from convention throughout the code.

### Binaries

| Binary | Role |
| --- | --- |
| `Eye-CareU.exe` | Qt 6 / QML application (QML is compiled in; 43 embedded `<VCPTree>` capability schemas). Build path leaked: `D:/01_program/EyeCare/setup/win64/build/bin`. |
| `EcShared.dll` | BenQ framework: `EcMonitorModel`, `EcVCPNode`, `EcModelModuleInterface`, `EcStateMachine`, `EcServerLocation`, GA/Matomo telemetry. |
| `Monitor.dll` | DDC/CI engine: `MonitorManager`, `MonitorModel`, `VCPNode`, `EDIDParser`. |
| `XCore.dll` | Internal Qt helper framework (`XCore*`). |

### DDC/CI VCP codes (from `Monitor.dll`)

| Feature | VCP | Notes |
| --- | --- | --- |
| Brightness | `0x10` | `getBrightness` / `setBrightness` |
| Volume | `0x62` | |
| Mute | `0x8D` | `1` = muted, `2` = unmuted |
| Picture mode | `0xDC` | 16-bit value; the mode is the low byte |
| OSD lock/status | `0xCA` | |
| Firmware version | `0xC9` | |
| Picture blank | `0xF6` | |
| VCP version probe | `0xDF` | used as the DDC link test |
| Factory reset | `0x04` / `0x08` | |

Picture-mode values for `0xDC`: **Standard `0x00`**, **Care Mode `0x01`**,
**Game `0x28`**, **Cinema `0x32`** (plus common MCCS extras).

Contrast (`0x12`) and the remaining MCCS codes in `eyecareu/mccs.py` are
standard-convention defaults, **not** observed BenQ behaviour. The BenQ vendor
codes (Brightness-Intelligence `0xE3`, Low Blue Light `0xE9`, Low-Light Sensor
`0xEB`) are *not* present in the binaries either — on Windows those features are
applied through ICC colour profiles (`EcVCPNode.currentIccProfile`), so this
port configures vendor codes per model and treats them as optional.

### Feature gating

The 43 embedded model schemas reduce to **five distinct feature signatures**
over nine tokens (`BI Type`, `BI Sensor`, `Brightness`,
`BrightnessForcePauseSyncTime`, `LowBlueLight`, `LowLightReminderEnable`,
`SetOsdPivot`, `Volume`, `MaxVolume`). `eyecareu/models.py` records these
signatures; at runtime the port decides support from the monitor's own MCCS
capability string and EDID instead of a hard-coded table.

### Feature inventory

Brightness, Volume, Low Blue Light, Night Light, Software Dimming, Warm Tint
(Windows 11 only), Circadian mode, 20-20-20 timer, Pomodoro, Pivot, ClearType
Text, Brightness Intelligence (BI/BI+), DPI/Resolution, Low-Light Reminder,
Break Reminder, Distance Reminder (removed in Windows v1.3.3.0), Screen-Time
report, Ambient Light, Visual Optimizer, Scaled Resolution.

---

## Feature parity

| Windows feature | Linux implementation | Status |
| --- | --- | --- |
| Brightness / Volume / Mute (DDC/CI) | `ddc` package (i2c-dev or `ddcutil`) | ✅ |
| Picture mode (DDC/CI `0xDC`) | `MonitorManager.set_color_mode` | ✅ |
| Night light | X11 gamma ramp (`display/gamma.py`) | ✅ (X11) |
| Low blue light | Gamma-ramp blue attenuation | ✅ (X11) |
| Software dimming | Gamma-ramp brightness scaling | ✅ (X11) |
| Warm tint | Gamma-ramp warm shift | ✅ |
| ClearType text | Mild gamma/contrast ramp | ✅ |
| Circadian mode | Local schedule or solar times | ✅ |
| 20-20-20 timer | `features/timers.py` + break overlay | ✅ |
| Pomodoro timer | `features/timers.py` (short/long breaks) | ✅ |
| Break reminder | `features/reminders.py` | ✅ |
| Low-light reminder | Condition reminder (ambient sensor) | ⚠️ needs a sensor |
| Distance / posture reminders | Interval reminders | ✅ |
| Screen-time report | `features/report.py` (+ 7-day view) | ✅ |
| Tray icon & menu | `tray.py` | ✅ |
| Autostart | XDG autostart (`autostart.py`) | ✅ |
| Ambient light / BI | Optional vendor VCP (per-model) | ⚠️ model-dependent |
| Telemetry (GA/Matomo) | Not implemented; opt-in flag defaults off | ➖ |

---

## Install (Fedora)

```bash
git clone <this-repo> eyecareu-linux
cd eyecareu-linux
./install-fedora.sh              # per-user install (recommended)
# or: ./install-fedora.sh --system
```

The script installs `python3-pyside6`, `ddcutil`, `i2c-tools`, `xrandr` and
`xprintidle`, drops the udev rule that lets your user talk to `/dev/i2c-*`,
installs the Python package, and registers the desktop entry and icon.

> After the udev rule is installed, **log out and back in** (or run
> `newgrp i2c`) so your user joins the `i2c` group.

### Manual install

```bash
python3 -m pip install --user .
# optional, only for a manual udev setup:
sudo install -m 0644 packaging/99-eyecareu-i2c.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### Run

```bash
eyecareu              # window
eyecareu --tray       # start in the system tray
eyecareu --minimised  # start hidden
eyecareu --doctor     # diagnose session, groups, colour backend and monitors
python3 -m eyecareu   # without installing
```

`--doctor` prints exactly what the app can do on this machine: the session
type, whether the `i2c`/`video` groups are active, which colour backend was
chosen, and what every detected monitor answers over DDC/CI. Run it first when
something looks wrong.

---

## How it works

```
eyecareu/
├── mccs.py            VCP code table + provenance
├── models.py          recovered per-model capability signatures
├── config.py          JSON settings (~/.config/eyecareu/config.json)
├── autostart.py       XDG autostart integration
├── core.py            EyeCareCore QObject exposed to QML
├── tray.py            QSystemTrayIcon + menu (icon painted at runtime)
├── app.py             bootstrap: QApplication + QQmlApplicationEngine
├── ddc/
│   ├── base.py        backend ABC, MonitorIdentity, VcpValue
│   ├── discovery.py   sysfs DRM/EDID/i2c detection
│   ├── edid.py        EDID parser
│   ├── i2c.py         raw DDC/CI over /dev/i2c-* (no dependencies)
│   ├── ddcutil.py     backend delegating to the ddcutil CLI
│   ├── backlight.py   sysfs /sys/class/backlight backend (internal panels)
│   └── manager.py     backend selection + capability resolution
├── display/
│   ├── session.py     X11/Wayland detection, output enumeration
│   ├── gamma.py       XRandR gamma ramps via ctypes + colour maths
│   ├── hyprsunset.py  real colour temperature + gamma on Hyprland (CTM)
│   └── effects.py     night light / low blue light / dimming / warm tint
├── features/
│   ├── timers.py      20-20-20 and Pomodoro phase machines
│   ├── reminders.py   break / low-light / distance / posture reminders
│   ├── circadian.py   scheduled colour temperature, solar times
│   └── report.py      screen-time accounting + report statistics
├── regroup.py         activate freshly-granted i2c/video groups via 'sg'
├── doctor.py          '--doctor' self-diagnosis
└── qml/               Qt Quick UI (theme, components, pages, popups)
```

* **DDC/CI** uses `ddcutil` when installed (it handles more adapters), and the
  built-in raw `i2c-dev` backend otherwise. Capability strings are read from the
  panel and resolved into an Eye-Care capability set. Reads and writes follow the
  VESA DDC/CI 1.1 packet format; because many panels never acknowledge a
  `Set VCP Feature`, a silent bus after a write is treated as success (a
  positive acknowledgement is still honoured when one is sent).
* **Software effects** are dispatched to the best backend for the session:
  * **Hyprland** — real, whole-screen colour temperature *and* dimming through
    the `hyprland-ctm-control-v1` protocol, driven by the `hyprsunset` daemon
    (`hyprctl hyprsunset temperature|gamma|identity`). No overlay, no X11.
  * **X11** — XRandR CRTC gamma ramps through `libX11` / `libXrandr` with ctypes.
  * **Other Wayland** — a last-resort translucent overlay (limited; see below).
* **Groups** — when the user has just been added to `i2c`/`video`, their running
  session does not have those supplementary groups yet. `regroup.py` re-executes
  the app through the setuid `sg` helper once, so DDC/CI works immediately
  instead of after a logout. Disable with `EYECAREU_NO_REGROUP=1`.
* **State** lives in `~/.config/eyecareu/config.json` and
  `~/.local/state/eyecareu/screentime.json`; writes are atomic and debounced.

### Session support

| Capability | X11 | Wayland (Hyprland) | Wayland (other) |
| --- | --- | --- | --- |
| DDC/CI monitor control | ✅ | ✅ | ✅ |
| Colour temperature + dimming | ✅ gamma ramp | ✅ real (hyprsunset) | ➖ overlay only |
| Tray, timers, reminders, report | ✅ | ✅ | ✅ |

On Hyprland, `hyprsunset` provides genuine per-output colour transformation, so
night light, low blue light, warm tint, circadian mode and software dimming all
change the real screen. On other Wayland compositors there is no portable
gamma API, so only a translucent overlay is possible (it cannot be positioned
without layer-shell, so it is best-effort). On X11 the gamma ramp is used.

> **Internal laptop panels** do not speak DDC/CI. They are controlled through
> `/sys/class/backlight`, which needs the shipped udev rule to have been
> triggered once (`sudo udevadm trigger --action=add --subsystem-match=backlight`)
> or a reboot after installation, plus membership of the `video` group.

---

## Development

```bash
python3 -m unittest discover -s tests -v   # 33 unit tests, no hardware needed
python3 -m eyecareu                         # run from a checkout
```

The pure-logic layers (timers, reminders, circadian, report, EDID, colour
maths, config, DDC packet handling, group logic) are clock- and
hardware-independent, so the tests run anywhere.

---

## Limitations

* **Wayland gamma:** real colour control needs Hyprland's CTM protocol
  (`hyprsunset`) or X11 gamma ramps. Other Wayland compositors get a best-effort
  overlay, and the UI says so.
* **Internal panels:** need the backlight udev rule to be triggered once and
  `video` group membership; external monitors use DDC/CI.
* **Vendor features:** Brightness Intelligence, ambient light and the BenQ
  low-blue-light hardware modes depend on vendor VCP codes that vary per model
  and are not confirmed in the binaries; set them per model in the config.
* **No telemetry:** the Windows build's Google Analytics / Matomo reporting is
  intentionally not implemented.

## License

MIT. This is an independent reimplementation for interoperability; it ships no
BenQ code or assets.
