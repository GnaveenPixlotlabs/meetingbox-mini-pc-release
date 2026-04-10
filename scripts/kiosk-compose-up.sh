#!/usr/bin/env bash
# Wait for local X11 + a usable MIT cookie, allow Docker to connect, then docker compose up -d.
# Used by systemd meetingbox-appliance.service (do not run with sudo — the unit runs as the GUI user).
#
# Copies the working cookie to APPLIANCE_DIR/.meetingbox-docker.xauth and passes that path as
# XAUTHORITY_HOST for this invocation so the device-ui bind mount matches GDM/Ubuntu 24 setups.

set -euo pipefail

APPLIANCE_DIR="${1:-${APPLIANCE_DIR:-$HOME/meetingbox-mini-pc-release}}"
APPLIANCE_DIR=$(cd "$APPLIANCE_DIR" && pwd)
COMPOSE_FILE="$APPLIANCE_DIR/docker-compose.yml"
XAUTH_COPY="$APPLIANCE_DIR/.meetingbox-docker.xauth"
u_id="$(id -u)"

if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "kiosk-compose-up: no docker-compose.yml in $APPLIANCE_DIR" >&2
  exit 1
fi

wait_for_x_socket() {
  local max="${1:-120}"
  local i
  for ((i = 1; i <= max; i++)); do
    if [[ -S /tmp/.X11-unix/X0 ]]; then
      echo ":0"
      return 0
    fi
    if [[ -S /tmp/.X11-unix/X1 ]]; then
      echo ":1"
      return 0
    fi
    sleep 1
  done
  return 1
}

pick_cookie_source() {
  local gdm="/run/user/${u_id}/gdm/Xauthority"
  if [[ -f "$gdm" && -s "$gdm" ]]; then
    echo "$gdm"
    return 0
  fi
  if [[ -f "$HOME/.Xauthority" && -s "$HOME/.Xauthority" ]]; then
    echo "$HOME/.Xauthority"
    return 0
  fi
  return 1
}

echo "kiosk-compose-up: waiting for X11 socket (max ~120s)..."
if ! disp_num=$(wait_for_x_socket 120); then
  echo "kiosk-compose-up: timed out waiting for /tmp/.X11-unix/X0 or X1" >&2
  exit 1
fi

echo "kiosk-compose-up: waiting for Xauthority cookie..."
src=""
for _try in $(seq 1 60); do
  if src=$(pick_cookie_source); then
    break
  fi
  sleep 2
done
if [[ -z "${src:-}" ]]; then
  echo "kiosk-compose-up: no usable cookie in /run/user/${u_id}/gdm/Xauthority or ~/.Xauthority" >&2
  echo "kiosk-compose-up: enable auto-login for this user or log in once on the built-in screen, then reboot." >&2
  exit 1
fi

export DISPLAY="$disp_num"
export XAUTHORITY="$src"
if /usr/bin/xhost "+local:docker" 2>/dev/null; then
  echo "kiosk-compose-up: xhost +local:docker ok"
else
  echo "kiosk-compose-up: xhost failed (continuing — cookie copy may still be enough)" >&2
fi

cp "$src" "$XAUTH_COPY"
chmod 600 "$XAUTH_COPY"

cd "$APPLIANCE_DIR"
# Shell env overrides .env for this run — bind mount + DISPLAY match what we waited for.
export XAUTHORITY_HOST="$XAUTH_COPY"
export DEVICE_UI_DISPLAY="$disp_num"
exec /usr/bin/docker compose up -d
