#!/usr/bin/env bash
# Install Eye-CareU for Linux on Fedora (and compatible distributions).
#
# It installs the runtime dependencies, the udev rule that grants your user
# access to the DDC/CI i2c buses, and the Python package itself.
#
# Usage:
#   ./install-fedora.sh            # per-user install (recommended)
#   ./install-fedora.sh --system   # system-wide install (needs sudo)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="user"
if [[ "${1:-}" == "--system" ]]; then
    MODE="system"
fi

say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }

# --------------------------------------------------------------------------
# 1. System packages
# --------------------------------------------------------------------------
PKGS=(python3-pyside6 python3-pip ddcutil i2c-tools xrandr xprintidle)
say "Installing system packages: ${PKGS[*]}"
if command -v dnf >/dev/null 2>&1; then
    if [[ "$MODE" == "system" ]]; then
        sudo dnf install -y "${PKGS[@]}" || warn "some packages failed to install"
    else
        sudo dnf install -y "${PKGS[@]}" || warn "some packages failed to install"
    fi
else
    warn "dnf not found; install equivalents of: ${PKGS[*]}"
fi

# --------------------------------------------------------------------------
# 2. udev rule so the user can talk to /dev/i2c-* (DDC/CI)
# --------------------------------------------------------------------------
RULE_SRC="${SCRIPT_DIR}/packaging/99-eyecareu-i2c.rules"
RULE_DST="/etc/udev/rules.d/99-eyecareu-i2c.rules"
if [[ -f "$RULE_SRC" ]]; then
    say "Creating the 'i2c' group and adding $USER to i2c and video"
    sudo groupadd -f i2c || true
    sudo usermod -aG i2c,video "$USER" || true

    say "Installing udev rule -> ${RULE_DST}"
    sudo install -m 0644 "$RULE_SRC" "$RULE_DST"
    sudo udevadm control --reload-rules || true
    # 'trigger' emits 'change' events by default; also force 'add' so the
    # backlight rule (add|change) re-applies without a reboot.
    sudo udevadm trigger || true
    sudo udevadm trigger --action=add --subsystem-match=backlight || true
    sudo udevadm trigger --action=add --subsystem-match=i2c-dev || true
    warn "Log out and back in for group membership to apply (the app also"
    warn "re-execs through 'sg' automatically, so it works immediately)."
fi

# --------------------------------------------------------------------------
# 3. Python package
# --------------------------------------------------------------------------
cd "$SCRIPT_DIR"
if [[ "$MODE" == "system" ]]; then
    say "Installing the Python package system-wide"
    sudo python3 -m pip install --break-system-packages .
else
    say "Installing the Python package for the current user"
    python3 -m pip install --user .
fi

# --------------------------------------------------------------------------
# 4. Desktop entry
# --------------------------------------------------------------------------
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
install -m 0644 "${SCRIPT_DIR}/packaging/eyecareu.desktop" "${APPS_DIR}/eyecareu.desktop"
say "Installed desktop entry to ${APPS_DIR}/eyecareu.desktop"

ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$ICON_DIR"
install -m 0644 "${SCRIPT_DIR}/packaging/icons/eyecareu.svg" "${ICON_DIR}/eyecareu.svg"
command -v gtk-update-icon-cache >/dev/null 2>&1 && \
    gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
say "Installed icon to ${ICON_DIR}/eyecareu.svg"

say "Done."
cat <<'EOF'

Next steps:
  * Run 'eyecareu' from a terminal or launch "Eye-CareU" from your applications.
  * Enable "Start Eye-CareU at login" in Settings, or copy
    packaging/eyecareu.desktop to ~/.config/autostart to start in the tray.
  * If DDC/CI controls are greyed out, confirm your user is in the 'i2c' group
    (run: groups) and that the monitor allows DDC/CI in its OSD menu.
EOF
