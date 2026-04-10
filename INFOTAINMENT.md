# Infotainment-style boot (one app, no Ubuntu desktop)

Goal: power on → **MeetingBox fullscreen** in Docker, **without** GNOME (no dock, Activities, or normal Ubuntu desktop). Under the hood it is still Linux + Docker (like many car head units).

## One command (after `.env` exists)

```bash
cd ~/meetingbox-mini-pc-release

# Once: create config (BACKEND_URL, COMPOSE_PROFILES=mini-pc,docker-audio, XAUTHORITY_HOST, …)
cp -n .env.example .env && nano .env

# Once: Docker permission for the GUI user
sudo usermod -aG docker meetingbox
# log out/in or reboot so group applies, then:

sudo bash scripts/setup-infotainment-kiosk.sh
sudo reboot
```

What this installs:

| Piece | Role |
|--------|------|
| **MeetingBox Kiosk** (GDM X session) | Black screen + Openbox; no full Ubuntu session |
| **`/etc/gdm3/custom.conf`** | Auto-login straight into `meetingbox-kiosk` |
| **`meetingbox-docker-audio.service`** | Redis + audio containers at **multi-user** (no display needed) |
| **`meetingbox-appliance.service`** | After graphical boot: cookie + `docker compose up -d` (UI + stack) |

## What you will still see

- Motherboard / UEFI logo  
- Short **kernel / Plymouth** (optional: `quiet splash` in GRUB)  
- A **brief** GDM/video-mode moment before the black screen  

Removing **all** branding needs a custom OEM image, not this repo alone.

## SSH recovery (panel blank / no Docker)

```bash
cd ~/meetingbox-mini-pc-release
bash scripts/recovery-appliance-ssh.sh
sudo systemctl start meetingbox-docker-audio meetingbox-appliance
docker ps
```

## Back to normal Ubuntu desktop

1. Remove the block between `# --- MeetingBox kiosk autologin ---` and `# --- end MeetingBox ---` in `/etc/gdm3/custom.conf` (backups: `*.bak-meetingbox-*` nearby).  
2. Edit `/var/lib/AccountsService/users/meetingbox` → `XSession=ubuntu` (or delete the `XSession=` line).  
3. `sudo reboot`

## Even less GDM (advanced)

To avoid the GDM greeter entirely, see **Level B** in `README.md` (`install-xinit-no-gdm.sh`). Keep SSH working before trying.
