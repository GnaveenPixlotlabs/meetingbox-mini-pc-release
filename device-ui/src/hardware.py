"""
Hardware utilities for Linux display power and brightness control.

Uses the standard Linux backlight sysfs interface when available and
falls back to X11 DPMS commands for screen power control.
"""

import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

BACKLIGHT_ROOT = Path("/sys/class/backlight")


def _x11_env() -> dict:
    """Env for xset: same DISPLAY as the running app, not hard-coded :0."""
    env = os.environ.copy()
    if not env.get("DISPLAY"):
        env["DISPLAY"] = ":0"
    return env

BRIGHTNESS_MAP = {
    "low": 0.30,
    "medium": 0.65,
    "high": 1.0,
}


def _find_path(name: str) -> Path | None:
    if not BACKLIGHT_ROOT.exists():
        return None
    for entry in sorted(BACKLIGHT_ROOT.iterdir()):
        p = entry / name
        if p.exists():
            return p
    return None


def _get_max_brightness() -> int:
    p = _find_path("max_brightness")
    if p:
        try:
            return int(p.read_text().strip())
        except Exception:
            pass
    return 255


def set_brightness(level: str) -> None:
    """Set display brightness. level: 'low', 'medium', or 'high'."""
    fraction = BRIGHTNESS_MAP.get(level, 1.0)
    max_br = _get_max_brightness()
    value = max(1, int(max_br * fraction))
    bp = _find_path("brightness")
    if not bp:
        logger.debug("No backlight sysfs found — skipping brightness change")
        return
    try:
        bp.write_text(str(value))
        logger.info("Brightness set to %s (%d/%d)", level, value, max_br)
    except PermissionError:
        try:
            subprocess.run(
                ["sudo", "tee", str(bp)],
                input=str(value).encode(), capture_output=True, timeout=5,
            )
            logger.info("Brightness set via sudo to %s (%d/%d)", level, value, max_br)
        except Exception as e:
            logger.warning("Failed to set brightness: %s", e)
    except Exception as e:
        logger.warning("Failed to set brightness: %s", e)


def screen_off() -> None:
    """Turn the display backlight off."""
    bp = _find_path("bl_power")
    if bp:
        try:
            bp.write_text("1")
            return
        except PermissionError:
            try:
                subprocess.run(
                    ["sudo", "tee", str(bp)],
                    input=b"1", capture_output=True, timeout=5,
                )
                return
            except Exception:
                pass
        except Exception:
            pass
    try:
        subprocess.run(
            ["xset", "dpms", "force", "off"],
            capture_output=True, timeout=5,
            env=_x11_env(),
        )
    except Exception as e:
        logger.debug("screen_off fallback failed: %s", e)


def screen_on(level: str = "high") -> None:
    """Turn the display backlight on and restore brightness."""
    bp = _find_path("bl_power")
    if bp:
        try:
            bp.write_text("0")
        except PermissionError:
            try:
                subprocess.run(
                    ["sudo", "tee", str(bp)],
                    input=b"0", capture_output=True, timeout=5,
                )
            except Exception:
                pass
        except Exception:
            pass
    else:
        try:
            subprocess.run(
                ["xset", "dpms", "force", "on"],
                capture_output=True, timeout=5,
                env=_x11_env(),
            )
        except Exception:
            pass
    set_brightness(level)


def _local_power_skip() -> bool:
    """Skip host power commands (e.g. desktop dev on Windows, or tests)."""
    if sys.platform.startswith("win"):
        return True
    v = os.environ.get("MEETINGBOX_SKIP_LOCAL_POWER", "").strip().lower()
    return v in ("1", "true", "yes")


def _running_in_container() -> bool:
    """True when UI runs in Docker — in-container systemctl does not reboot the host."""
    try:
        return Path("/.dockerenv").exists()
    except OSError:
        return False


def _run_host_helper_script(path: str) -> bool:
    """Run a shell script that reboots/shuts down the host (nsenter wrapper)."""
    p = Path(path)
    if not p.is_file():
        return False
    try:
        proc = subprocess.Popen(
            ["/bin/sh", str(p)], close_fds=True, start_new_session=True
        )
        time.sleep(0.2)
        code = proc.poll()
        if code is not None and code != 0:
            logger.warning("Host helper %s exited immediately with code %s", path, code)
            return False
        logger.info("Host helper started: %s", path)
        return True
    except Exception as e:
        logger.debug("host helper %s: %s", path, e)
        return False


def _run_reboot_argv(args: list[str]) -> bool:
    """Run a reboot argv; require exit 0 (Popen alone can lie inside containers)."""
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=12,
        )
        if r.returncode == 0:
            logger.info("Reboot requested via %s", args)
            return True
        err = (r.stderr or r.stdout or "").strip()
        if err:
            logger.debug("reboot %s failed rc=%s: %s", args, r.returncode, err[:200])
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        logger.debug("reboot %s timed out (treat as failure; may be waiting for password)", args)
    except Exception as e:
        logger.debug("reboot %s: %s", args, e)
    return False


def _run_poweroff_argv(args: list[str]) -> bool:
    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=12,
        )
        if r.returncode == 0:
            logger.info("Poweroff requested via %s", args)
            return True
        err = (r.stderr or r.stdout or "").strip()
        if err:
            logger.debug("poweroff %s failed rc=%s: %s", args, r.returncode, err[:200])
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        logger.debug("poweroff %s timed out (treat as failure)", args)
    except Exception as e:
        logger.debug("poweroff %s: %s", args, e)
    return False


def request_system_reboot() -> bool:
    """
    Reboot the machine that runs this UI (mini-PC / kiosk host).

    The web API often runs in Docker without permission to reboot the host; the
    appliance UI process runs on the host and can invoke systemd/sudo the same
    way brightness uses sudo tee.
    """
    if _local_power_skip():
        logger.debug("Local reboot skipped (Windows or MEETINGBOX_SKIP_LOCAL_POWER)")
        return False

    env_cmd = (os.environ.get("MEETINGBOX_LOCAL_REBOOT_CMD") or "").strip()
    if env_cmd:
        try:
            subprocess.Popen(env_cmd, shell=True, close_fds=True, start_new_session=True)
            logger.info("Reboot requested via MEETINGBOX_LOCAL_REBOOT_CMD")
            return True
        except Exception as e:
            logger.warning("MEETINGBOX_LOCAL_REBOOT_CMD failed: %s", e)

    helper_env = (os.environ.get("MEETINGBOX_LOCAL_REBOOT_HELPER") or "").strip()
    for hp in {h for h in (helper_env, "/usr/local/bin/meetingbox-host-reboot") if h}:
        if _run_host_helper_script(hp):
            return True

    in_container = _running_in_container()
    if in_container:
        logger.warning(
            "Reboot from container: no MEETINGBOX_LOCAL_REBOOT_CMD / host helper worked. "
            "Mount /usr/local/bin/meetingbox-host-reboot from the host, or set "
            "MEETINGBOX_LOCAL_REBOOT_CMD (e.g. nsenter … systemctl reboot). "
            "The app will try the backend PATCH /api/device/settings next."
        )
        return False

    candidates: list[list[str]] = []
    if os.geteuid() == 0:
        rb = shutil.which("reboot") or "/sbin/reboot"
        candidates.append([rb])
    candidates.extend(
        [
            ["systemctl", "reboot"],
            ["sudo", "-n", "systemctl", "reboot"],
            ["sudo", "-n", "reboot"],
            ["sudo", "-n", "shutdown", "-r", "now"],
        ]
    )
    for args in candidates:
        if _run_reboot_argv(args):
            return True
    logger.warning(
        "Local reboot not started — allow systemctl reboot or passwordless sudo "
        "for this user (see sudoers / polkit)."
    )
    return False


def request_system_poweroff() -> bool:
    """Power off the machine that runs this UI."""
    if _local_power_skip():
        logger.debug("Local poweroff skipped (Windows or MEETINGBOX_SKIP_LOCAL_POWER)")
        return False

    env_cmd = (os.environ.get("MEETINGBOX_LOCAL_POWEROFF_CMD") or "").strip()
    if env_cmd:
        try:
            subprocess.Popen(env_cmd, shell=True, close_fds=True, start_new_session=True)
            logger.info("Poweroff requested via MEETINGBOX_LOCAL_POWEROFF_CMD")
            return True
        except Exception as e:
            logger.warning("MEETINGBOX_LOCAL_POWEROFF_CMD failed: %s", e)

    helper_env = (os.environ.get("MEETINGBOX_LOCAL_POWEROFF_HELPER") or "").strip()
    for hp in {h for h in (helper_env, "/usr/local/bin/meetingbox-host-poweroff") if h}:
        if _run_host_helper_script(hp):
            return True

    if _running_in_container():
        logger.warning(
            "Poweroff from container: set MEETINGBOX_LOCAL_POWEROFF_CMD or mount "
            "meetingbox-host-poweroff from the host, or rely on backend PATCH."
        )
        return False

    candidates: list[list[str]] = []
    if os.geteuid() == 0:
        po = shutil.which("poweroff") or "/sbin/poweroff"
        candidates.append([po])
    candidates.extend(
        [
            ["systemctl", "poweroff"],
            ["sudo", "-n", "systemctl", "poweroff"],
            ["sudo", "-n", "poweroff"],
            ["sudo", "-n", "shutdown", "-h", "now"],
        ]
    )
    for args in candidates:
        if _run_poweroff_argv(args):
            return True
    logger.warning(
        "Local poweroff not started — allow systemctl poweroff or passwordless sudo."
    )
    return False
