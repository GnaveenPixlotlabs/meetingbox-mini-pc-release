"""
On-device WiFi via NetworkManager (nmcli).

Used by WiFi setup and Settings → WiFi so scans work when BACKEND_URL points at a
remote server (the API cannot see the mini-PC's wlan0).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def has_nmcli() -> bool:
    return shutil.which("nmcli") is not None


def nmcli_run(args: list, timeout: float = 30):
    """
    Run nmcli; on PolicyKit denial retry with sudo -n nmcli (passwordless sudoers).
    """
    cmd = ["nmcli"] + args
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    combined = ((res.stderr or "") + (res.stdout or "")).lower()
    priv = any(
        s in combined
        for s in (
            "insufficient privileges",
            "not authorized",
            "permission denied",
            "not allowed to",
            "polkit",
        )
    )
    if res.returncode != 0 and priv and shutil.which("sudo"):
        res2 = subprocess.run(
            ["sudo", "-n", "nmcli"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        sudo_msg = ((res2.stderr or "") + (res2.stdout or "")).lower()
        if res2.returncode != 0 and any(
            s in sudo_msg
            for s in (
                "a password is required",
                "password is required",
                "terminal is required",
                "no tty present",
                "sudo: a password",
            )
        ):
            return res
        return res2
    return res


def detect_wifi_iface() -> Optional[str]:
    if not has_nmcli():
        return None
    try:
        res = nmcli_run(
            ["-t", "-f", "DEVICE,TYPE,STATE", "device", "status"],
            timeout=6,
        )
        for line in res.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] == "wifi":
                return parts[0]
    except Exception:
        return None
    return None


def scan_wifi_networks(rescan: bool = False) -> list[dict]:
    if not has_nmcli():
        raise RuntimeError("nmcli not available")
    if rescan:
        try:
            nmcli_run(["device", "wifi", "rescan"], timeout=10)
        except Exception:
            pass

    res = nmcli_run(
        [
            "-m",
            "multiline",
            "-f",
            "SSID,SIGNAL,SECURITY,IN-USE",
            "device",
            "wifi",
            "list",
        ],
        timeout=15,
    )
    nets: list[dict] = []
    cur: dict[str, str] = {}

    def flush_current():
        ssid = (cur.get("SSID") or "").strip()
        if not ssid:
            return
        signal_raw = (cur.get("SIGNAL") or "0").strip()
        sec_raw = (cur.get("SECURITY") or "").strip()
        in_use = (cur.get("IN-USE") or "").strip()
        try:
            signal = int(signal_raw) if signal_raw else 0
        except ValueError:
            signal = 0
        nets.append(
            {
                "ssid": ssid,
                "signal_strength": signal,
                "security": sec_raw or "open",
                "connected": in_use == "*",
            }
        )

    for line in res.stdout.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        key = k.strip()
        val = v.strip()
        if key == "SSID" and "SSID" in cur:
            flush_current()
            cur = {}
        cur[key] = val

    flush_current()
    return nets


def connect_wifi_network(ssid: str, password: Optional[str]) -> dict:
    iface = detect_wifi_iface()
    args = ["device", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    if iface:
        args += ["ifname", iface]
    res = nmcli_run(args, timeout=30)
    if res.returncode == 0:
        return {"status": "connected", "message": f"Connected to {ssid}"}
    msg = (res.stderr or "").strip() or (res.stdout or "").strip() or "Connection failed"
    ml = msg.lower()
    if "password" not in ml and "802" not in ml:
        if any(s in ml for s in ("sudo", "privileges", "not authorized", "polkit")):
            msg += (
                "\n\nWiFi needs NetworkManager permission on this device. "
                "See scripts/sudoers.meetingbox-nmcli.example or scripts/polkit/"
            )
    return {"status": "failed", "message": msg}
