# MeetingBox mini PC (appliance)

This folder contains everything that normally runs on the **meeting room device**: the **Kivy device UI** and the **audio capture** stack. The FastAPI dashboard lives in **`server/`** in the main repo (or your VPS uses a server-only clone).

## Contents

| Path | Purpose |
|------|---------|
| `device-ui/` | Touch/kiosk UI (Python/Kivy) |
| `audio/` | Mic capture, VAD, WAV upload (`run_audio_capture.sh` + Docker image) |
| `docker-compose.yml` | Optional: run UI and/or Docker audio on the device |
| `.env.example` | All appliance env vars — copy to `.env` |
| `scripts/install-boot-service.sh` | **systemd**: start the Compose stack at boot (kiosk) |

## Quick start (mini PC only)

```bash
cd mini-pc
cp .env.example .env
nano .env   # BACKEND_URL, BACKEND_WS_URL, UPLOAD_AUDIO_API_URL, DASHBOARD_URL
mkdir -p data/audio/recordings data/audio/temp data/config
```

**UI (recommended native):**

```bash
cd device-ui
cp .env.example .env   # optional per-app overrides
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
./run_device_ui.sh
```

**Mic (recommended host script):**

```bash
cd audio
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
# Ensure .env or exports: REDIS_HOST, UPLOAD_AUDIO_API_URL, DEVICE_AUTH_TOKEN after pairing
./run_audio_capture.sh
```

**UI + Docker mic** — `redis` and `audio` are gated by the **`docker-audio`** profile. Either set in `.env`:

```env
COMPOSE_PROFILES=mini-pc,docker-audio
```

or pass profiles on the CLI:

```bash
docker compose --profile mini-pc --profile docker-audio up -d --build
```

If you only set `COMPOSE_PROFILES=mini-pc`, the mic and Redis containers **will not start** (by design).

## Kiosk: fullscreen UI + start on boot

The device-ui image defaults to **borderless fullscreen** (`FULLSCREEN` defaults to `1` in `docker-compose.yml`). Override with `FULLSCREEN=0` in `.env` when developing on a desktop.

**Permanent X11 settings** belong in `.env` on the device (not only in your SSH shell): `DEVICE_UI_DISPLAY`, `XAUTHORITY_HOST`, and `FULLSCREEN=1`. Copy from `.env.example` and adjust the username in `XAUTHORITY_HOST`.

**systemd (after graphical login / auto-login):**

```bash
cd /path/to/meetingbox-mini-pc-release   # your install dir
cp .env.example .env   # if needed; edit BACKEND_URL, XAUTHORITY_HOST, etc.
sudo usermod -aG docker meetingbox        # GUI user; then re-login
sudo bash scripts/install-boot-service.sh  # optional: pass install dir as first arg
sudo systemctl start meetingbox-appliance
```

The unit enables `meetingbox-appliance.service` on **`graphical.target`**, sets `HOME`, then runs **`scripts/kiosk-compose-up.sh`**: it waits for `/tmp/.X11-unix`, copies the live cookie from **`/run/user/<uid>/gdm/Xauthority`** (Ubuntu/GDM) or **`~/.Xauthority`** into **`.meetingbox-docker.xauth`**, runs **`xhost +local:docker`**, and starts Compose with **`XAUTHORITY_HOST`** pointing at that file (so boot no longer races an empty home cookie).

Configure **automatic login** so GDM creates that session at boot; otherwise log in once on the panel after each reboot before the wait window (about two minutes) expires.

For a “single app” feel, hide or disable the host desktop panel/taskbar in your distro settings (MeetingBox still runs fullscreen in its own window). You will still see the Ubuntu desktop **briefly** while GNOME starts; that is normal unless you replace the session with a minimal window manager.

The boot script runs **`docker compose up -d` once** (no immediate `--force-recreate` of the UI) so the fullscreen app is not stopped and restarted a second time on every boot.

## Splitting into its own git repository

From the monorepo root (preserve history for this subtree):

```bash
git subtree split --prefix=mini-pc -b mini-pc-release
git push <your-appliance-remote> mini-pc-release:main
```

On the device, clone that repo and use only this directory — no `server/` or `frontend/` checkout required. (`run_device_ui.sh` / `run_audio_capture.sh` look for a sibling `server/docker-compose.yml` only to detect the full monorepo and load a parent `.env`; that path is absent in an appliance-only clone and scripts still work.)

## Monorepo usage

The parent **`docker-compose.yml`** still builds `mini-pc/device-ui` and `mini-pc/audio` when you use profiles `mini-pc` / `docker-audio` there. This folder’s `docker-compose.yml` is for **appliance-only** checkouts.
