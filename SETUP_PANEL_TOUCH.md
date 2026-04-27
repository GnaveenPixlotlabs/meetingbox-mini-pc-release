# Panel rotation + touchscreen — step by step

Do these **on the mini PC**, in order. Stop when touch works.

---

## Step 1 — Open the panel config

```bash
sudo mkdir -p /etc/meetingbox
sudo nano /etc/meetingbox/panel-xrandr.env
```

---

## Step 2 — Paste this block, then edit the two **bold** parts

**A.** If your screen is **DSI** and you use **rotate right** (common for portrait panels mounted landscape), use:

```bash
MEETINGBOX_PANEL_OUTPUT=DSI-1
MEETINGBOX_PANEL_MODE=800x1280
MEETINGBOX_PANEL_ROTATE=right
MEETINGBOX_MAP_TOUCH_TO_OUTPUT=1
```

**A2.** If the panel must use **rotate left** (90° CCW), set the **same** rotation for the **touch matrix** — add **`MEETINGBOX_TOUCH_MATRIX_PRESET=left`** (or the explicit matrix below). Example:

```bash
MEETINGBOX_PANEL_OUTPUT=DSI-1
MEETINGBOX_PANEL_MODE=800x1280
MEETINGBOX_PANEL_ROTATE=left
MEETINGBOX_MAP_TOUCH_TO_OUTPUT=1
MEETINGBOX_TOUCH_MATRIX_PRESET=left
```

Equivalent to the preset `left` (nine numbers):

```bash
MEETINGBOX_TOUCH_COORD_MATRIX="0 -1 1 1 0 0 0 0 1"
```

**A3.** If the **whole UI is upside down** (180°, top and bottom swapped), use **`inverted`** for both the panel and touch:

```bash
MEETINGBOX_PANEL_ROTATE=inverted
MEETINGBOX_TOUCH_MATRIX_PRESET=inverted
```

(Or only the matrix: `MEETINGBOX_TOUCH_COORD_MATRIX="-1 0 1 0 -1 1 0 0 1"`.)  
If it was only “sideways”, try **`left`** or **`right`** instead — not **`inverted`**.

**B.** Touch: use **numeric id** if you have Goodix twice (pointer vs keyboard). Run:

```bash
export DISPLAY=:0
xinput list
```

Find **Goodix** with **`slave  pointer`** — note **id=** (often **15**). **Ignore** the Goodix line under **`slave  keyboard`** (often **18**).

Add **this** to the same file (use your pointer id):

```bash
MEETINGBOX_TOUCH_XINPUT_ID=15
```

Or by **name** (only if one Goodix line):

```bash
MEETINGBOX_TOUCH_XINPUT_DEVICE='Goodix Capacitive TouchScreen'
```

Save: **Ctrl+O**, Enter, **Ctrl+X**.

---

## Step 3 — User must be in group `input` (once)

```bash
sudo usermod -aG input $USER
sudo reboot
```

(Or log out and log in completely after this.)

---

## Step 4 — Match app size to the real screen

```bash
nano ~/meetingbox-mini-pc-release/.env
```

Add or set:

```bash
MEETINGBOX_SYNC_DISPLAY_FROM_XRANDR=1
```

Save and exit.

---

## Step 5 — Install / refresh the orientation helper (if you use git)

```bash
cd ~/meetingbox-mini-pc-release
git pull
sudo install -m 0755 scripts/apply-kiosk-display-orientation.sh /usr/local/bin/meetingbox-apply-kiosk-display-orientation
```

---

## Step 6 — Restart the UI

```bash
cd ~/meetingbox-mini-pc-release
docker compose --profile mini-pc --profile docker-audio up -d device-ui
```

Or reboot:

```bash
sudo reboot
```

---

## Step 7 — If taps still hit the wrong place

Edit the panel file again:

```bash
sudo nano /etc/meetingbox/panel-xrandr.env
```

Add **one** of these (try after Step 6). **Always quote values with spaces.**  
The touch preset must **match** `MEETINGBOX_PANEL_ROTATE`: **`right`** with `rotate right`, **`left`** with `rotate left`.

```bash
MEETINGBOX_TOUCH_MATRIX_PRESET=right
```

Or for **rotate left** panels:

```bash
MEETINGBOX_TOUCH_MATRIX_PRESET=left
```

Or nine explicit numbers (quotes are **required**). **Right** (same as preset `right`):

```bash
MEETINGBOX_TOUCH_COORD_MATRIX="0 1 0 -1 0 1 0 0 1"
```

**Left** (same as preset `left`):

```bash
MEETINGBOX_TOUCH_COORD_MATRIX="0 -1 1 1 0 0 0 0 1"
```

Save and reboot. If it gets **worse**, swap `right` ↔ `left`, or **delete** the matrix line and reboot again.

**If the matrix “does not apply”**, common causes are:

1. **`xrandr` failed** (wrong `MEETINGBOX_PANEL_OUTPUT` / mode) — older scripts **skipped all touch steps** when `xrandr` failed. Update `scripts/apply-kiosk-display-orientation.sh` from the repo and reinstall it to `/usr/local/bin/meetingbox-apply-kiosk-display-orientation` (Step 5). Touch mapping now runs even when `xrandr` fails, and the matrix is applied even when `map-to-output` fails.
2. **`map-to-output` failed** — the matrix is still applied to your device after an attempted map (same script update).
3. **Unquoted matrix in `panel-xrandr.env`** — without quotes, only the first number is used. It must be exactly **nine** numbers:
   `MEETINGBOX_TOUCH_COORD_MATRIX="0 1 0 -1 0 1 0 0 1"`
4. **No pointer device** — set **`MEETINGBOX_TOUCH_XINPUT_ID`** to the **slave pointer** id from `xinput list` (Step 2).
5. **Confirm the script ran** — after login: `journalctl -t meetingbox-kiosk -b --no-pager | tail -30`  
   You should see either `Coordinate Transformation Matrix on '15': ...` or a clear `set ... failed` line.  
   On the panel: `xinput list-props 15 | grep -i Coordinate` (use your id).

---

## Step 8 — Still broken?

**A.** Collect a full report and share it:

```bash
cd ~/meetingbox-mini-pc-release
export DISPLAY=:0
bash scripts/diagnose-touch-panel.sh
```

**B.** Raw touch test (should print lines when you drag a finger on the glass):

```bash
export DISPLAY=:0
xinput test 15
```

(Use **15** or your pointer id from `xinput list`.)

**C.** If `xinput test` shows nothing, the kernel may not see touch — try `sudo evtest` and pick the Goodix event node.

**D.** Remove **matrix** if you added it and things got worse — edit `panel-xrandr.env`, delete `MEETINGBOX_TOUCH_MATRIX_PRESET`, reboot.

**E.** In **mini-pc `.env`**, keep **`MEETINGBOX_SYNC_DISPLAY_FROM_XRANDR=1`** so Kivy’s window size matches the real screen (wrong size = wrong button positions).

---

## One-page checklist

| Done | Task |
|------|------|
| ☐ | `/etc/meetingbox/panel-xrandr.env` created with DSI + rotate + `MEETINGBOX_TOUCH_XINPUT_DEVICE` |
| ☐ | `sudo usermod -aG input $USER` + reboot |
| ☐ | `MEETINGBOX_SYNC_DISPLAY_FROM_XRANDR=1` in `mini-pc/.env` |
| ☐ | `/usr/local/bin/meetingbox-apply-kiosk-display-orientation` installed from repo |
| ☐ | `device-ui` restarted or full reboot |
| ☐ | Optional: `MEETINGBOX_TOUCH_MATRIX_PRESET=right` |

More detail: **`INFOTAINMENT.md`**, template: **`kiosk-desktop/panel-xrandr.env.example`**.

---

## Rotation not applying (picture stays wrong / `xrandr` never sticks)

1. **Confirm the helper runs and log the error** (on the mini PC, after login):

   ```bash
   journalctl -t meetingbox-kiosk -b --no-pager | tail -50
   ```

   You should see either `xrandr ok: ...` or lines like `xrandr failed ...` plus a dump of `xrandr` output.

2. **Wrong output name** — On the **built-in screen** terminal (`DISPLAY=:0`):

   ```bash
   xrandr
   ```

   Use the **exact** connected output name in `panel-xrandr.env` (e.g. `HDMI-1`, `eDP-1`, `DSI-1`). Or set:

   ```bash
   MEETINGBOX_PANEL_OUTPUT=auto
   ```

   so the script picks the first **connected** line from `xrandr`.

3. **Wrong mode** — If `--mode 800x1280` fails, the script falls back to **rotate-only** and **`--auto --rotate`**. If all fail, set **`MEETINGBOX_PANEL_MODE`** to a mode that appears in `xrandr` for that output (or leave mode wrong and rely on `--auto` after script update).

4. **Disabled in config** — Ensure you do **not** have:

   ```bash
   MEETINGBOX_SKIP_PANEL_XRANDR=1
   ```

5. **Early X / GDM** — The script **retries** `xrandr` (default 30 attempts, 1 s apart). If the panel is very slow, add to `panel-xrandr.env`:

   ```bash
   MEETINGBOX_XRANDR_ATTEMPTS=60
   MEETINGBOX_XRANDR_RETRY_DELAY=1
   ```

6. **Refresh the installed script** after `git pull`:

   ```bash
   sudo install -m 0755 ~/meetingbox-mini-pc-release/scripts/apply-kiosk-display-orientation.sh /usr/local/bin/meetingbox-apply-kiosk-display-orientation
   ```

   Then reboot.
