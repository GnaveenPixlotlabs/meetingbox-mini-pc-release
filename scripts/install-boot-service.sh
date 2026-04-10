#!/usr/bin/env bash
# Install systemd unit so the appliance Compose stack starts at graphical boot (kiosk mini PC).
# Run on the device:  sudo bash scripts/install-boot-service.sh
# Optional path:       sudo bash scripts/install-boot-service.sh /home/meetingbox/meetingbox-mini-pc-release
#
# Requires: Docker + Compose v2, target user in the "docker" group, graphical auto-login so :0 + .Xauthority exist.

set -euo pipefail

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MINI_PC_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
RUN_AS_USER="${SUDO_USER:-${MEETINGBOX_USER:-meetingbox}}"
APPLIANCE_DIR="${1:-$MINI_PC_ROOT}"

if ! getent passwd "$RUN_AS_USER" &>/dev/null; then
  echo "User not found: $RUN_AS_USER (set SUDO_USER by using sudo, or MEETINGBOX_USER=name $0)" >&2
  exit 1
fi

RUN_AS_HOME=$(getent passwd "$RUN_AS_USER" | cut -d: -f6)
if [[ -z "$RUN_AS_HOME" || ! -d "$RUN_AS_HOME" ]]; then
  echo "No home directory for $RUN_AS_USER" >&2
  exit 1
fi

if [[ ! -f "$APPLIANCE_DIR/docker-compose.yml" ]]; then
  echo "No docker-compose.yml in: $APPLIANCE_DIR" >&2
  exit 1
fi

if ! id -nG "$RUN_AS_USER" | tr ' ' '\n' | grep -qx docker; then
  echo "WARNING: user '$RUN_AS_USER' is not in group 'docker'. Add with:" >&2
  echo "  sudo usermod -aG docker $RUN_AS_USER" >&2
  echo "then log out and back in, then re-run this script." >&2
fi

SERVICE_PATH=/etc/systemd/system/meetingbox-appliance.service
AUDIO_SERVICE=/etc/systemd/system/meetingbox-docker-audio.service

# Redis + mic: start at multi-user.target so they run even if GDM/kiosk/X never comes up.
cat >"$AUDIO_SERVICE" <<EOF
[Unit]
Description=MeetingBox Redis + audio (Docker, no display required)
After=docker.service network-online.target
Wants=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=$RUN_AS_USER
Group=$RUN_AS_USER
WorkingDirectory=$APPLIANCE_DIR
Environment=HOME=$RUN_AS_HOME
ExecStart=/usr/bin/docker compose --profile docker-audio up -d redis audio
TimeoutStartSec=120

[Install]
WantedBy=multi-user.target
EOF

# Full stack after graphical session (cookie + device-ui).
cat >"$SERVICE_PATH" <<EOF
[Unit]
Description=MeetingBox appliance (Docker Compose + UI)
Documentation=https://github.com/ (see mini-pc/README.md)
After=docker.service network-online.target display-manager.service meetingbox-docker-audio.service
Wants=docker.service network-online.target
After=graphical.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=$RUN_AS_USER
Group=$RUN_AS_USER
WorkingDirectory=$APPLIANCE_DIR
Environment=HOME=$RUN_AS_HOME
ExecStart=$APPLIANCE_DIR/scripts/kiosk-compose-up.sh $APPLIANCE_DIR
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=300

[Install]
WantedBy=graphical.target
EOF

systemctl daemon-reload
systemctl enable meetingbox-docker-audio.service meetingbox-appliance.service
echo "Installed and enabled:"
echo "  $AUDIO_SERVICE  (multi-user — redis + audio always)"
echo "  $SERVICE_PATH   (graphical — full stack + UI)"
echo "Start now:  sudo systemctl start meetingbox-docker-audio meetingbox-appliance"
echo "Logs:       journalctl -u meetingbox-docker-audio -u meetingbox-appliance -b"
