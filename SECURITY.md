# Security Policy

## Scope

Eye-CareU for Linux is a desktop application. Its security-relevant surface is
small and consists of:

* **Local hardware access** — DDC/CI over `/dev/i2c-*` and the sysfs backlight.
  These require membership of the `i2c` and `video` groups, granted by the
  shipped udev rule (`packaging/99-eyecareu-i2c.rules`). The rule only widens
  access to those specific device classes; it does not run as root.
* **Subprocess calls** — external helpers (`ddcutil`, `xrandr`, `wlr-randr`,
  `xprintidle`, `hyprctl`, `hyprsunset`, `sg`). Every call uses the list form of
  `subprocess` (no shell), so arguments are never interpreted by a shell.
* **Local configuration** — JSON under `~/.config/eyecareu/` and
  `~/.local/state/eyecareu/`.

The application performs **no network access**, contains **no telemetry**, and
stores no credentials. (The Windows build's Google Analytics / Matomo reporting
is deliberately not reimplemented.)

## Supported versions

Only the latest release on the default branch is supported with fixes.

## Reporting a vulnerability

Please report suspected vulnerabilities privately via GitHub's
[Security Advisories](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
("Report a vulnerability" on the repository's **Security** tab), or by opening a
minimal issue that does **not** include exploit details.

Do not open a public issue with a working exploit. We aim to acknowledge reports
within a few days.

## Hardening notes for users

* Prefer the per-user install (`./install-fedora.sh`) over `--system`.
* The `i2c` group grants read/write to the DDC/CI bus, which lets a local
  process change your monitor settings. Only add trusted users to it.
* If you do not need hardware control, the software-only eye-care features
  (timers, reminders, report, Hyprland/X11 colour effects) work without any
  elevated group membership.
