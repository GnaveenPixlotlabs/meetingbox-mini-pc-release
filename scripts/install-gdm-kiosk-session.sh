#!/usr/bin/env bash
# Install a minimal GDM session so the device boots straight into MeetingBox (no GNOME Shell).
#
#   sudo bash scripts/install-gdm-kiosk-session.sh [/home/meetingbox/meetingbox-mini-pc-release]
#
# After install: run install-boot-service.sh, then reboot (see setup-infotainment-kiosk.sh).

set -euo pipefail

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MINI_PC_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
APPLIANCE_DIR="${1:-$MINI_PC_ROOT}"
RUN_AS_USER="${SUDO_USER:-${MEETINGBOX_USER:-meetingbox}}"

if ! getent passwd "$RUN_AS_USER" &>/dev/null; then
  echo "User not found: $RUN_AS_USER" >&2
  exit 1
fi

APPLIANCE_DIR=$(cd "$APPLIANCE_DIR" && pwd)

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openbox x11-xserver-utils

install -m 0755 "$MINI_PC_ROOT/scripts/gdm-kiosk-session.sh" /usr/local/bin/meetingbox-gdm-kiosk-session
install -m 0644 "$MINI_PC_ROOT/kiosk-desktop/meetingbox-kiosk.desktop" /usr/share/xsessions/meetingbox-kiosk.desktop

mkdir -p /etc/meetingbox
echo "$APPLIANCE_DIR" >/etc/meetingbox/release
chmod 644 /etc/meetingbox/release

ASU="/var/lib/AccountsService/users/$RUN_AS_USER"
if [[ -f "$ASU" ]]; then
  cp -a "$ASU" "${ASU}.bak-meetingbox-$(date +%s)"
  if grep -q '^XSession=' "$ASU" 2>/dev/null; then
    sed -i 's/^XSession=.*/XSession=meetingbox-kiosk/' "$ASU"
  else
    printf '\nXSession=meetingbox-kiosk\n' >>"$ASU"
  fi
  echo "Set default X session for $RUN_AS_USER to meetingbox-kiosk in $ASU"
else
  echo "WARNING: no $ASU — create user or log in once, then re-run or add XSession=meetingbox-kiosk manually."
fi

# GDM: skip Ubuntu greeter / session list — jump straight into meetingbox-kiosk X session.
if [[ -f /etc/gdm3/custom.conf ]]; then
  bash "$MINI_PC_ROOT/scripts/patch-gdm-autologin-kiosk.sh" /etc/gdm3/custom.conf "$RUN_AS_USER"
else
  echo "WARNING: /etc/gdm3/custom.conf missing — set AutomaticLogin + AutomaticLoginSession=meetingbox-kiosk manually."
fi

echo ""
echo "Done."
echo "  1) sudo bash scripts/install-boot-service.sh   # REQUIRED: starts redis+audio without X; starts full stack after graphical"
echo "     Do NOT disable meetingbox-appliance until the kiosk session is verified — otherwise nothing starts Docker."
echo "  2) Reboot — auto-login should go to black screen + app, not the full Ubuntu dock."
echo "  3) If stuck: bash scripts/recovery-appliance-ssh.sh  (from SSH)"
echo "  4) Normal Ubuntu again: remove MeetingBox block from /etc/gdm3/custom.conf; set XSession=ubuntu in $ASU"
echo ""
echo "Still see GDM flash? Optional: scripts/install-xinit-no-gdm.sh (advanced)."
