#!/usr/bin/env bash
# GDM X session: no GNOME Shell — black screen, tiny Openbox, then Docker MeetingBox UI.
# Installed as /usr/local/bin/meetingbox-gdm-kiosk-session by install-gdm-kiosk-session.sh
#
# Keep this process running until logout, or GDM will end the session.

set +e

RELEASE="${MEETINGBOX_RELEASE:-$HOME/meetingbox-mini-pc-release}"
if [[ -f /etc/meetingbox/release ]]; then
  RELEASE=$(tr -d '\n' </etc/meetingbox/release)
fi
RELEASE=$(cd "$RELEASE" 2>/dev/null && pwd || echo "$RELEASE")

export PATH="/usr/sbin:/usr/bin:/usr/local/bin:$PATH"

# Solid black while Docker / UI start (no Ubuntu wallpaper or dock).
xsetroot -solid '#000000' 2>/dev/null || true

# Minimal WM so SDL/Kivy fullscreen behaves; ~2 MB RAM vs full GNOME.
if command -v openbox >/dev/null 2>&1; then
  openbox >/dev/null 2>&1 &
  sleep 0.2
fi

echo "meetingbox-gdm-kiosk: waiting for Docker..."
for _ in $(seq 1 120); do
  docker info &>/dev/null && break
  sleep 0.5
done

KOISK="$RELEASE/scripts/kiosk-compose-up.sh"
if [[ -f "$KOISK" ]]; then
  # shellcheck disable=SC1090
  bash "$KOISK" "$RELEASE" || logger -t meetingbox-kiosk "kiosk-compose-up exited $?"
else
  logger -t meetingbox-kiosk "missing $KOISK — set path in /etc/meetingbox/release"
fi

# Hold the X session open (required by GDM).
exec tail -f /dev/null
