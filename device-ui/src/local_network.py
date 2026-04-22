"""
Best-effort primary IPv4 for on-device status UI (e.g. home footer).

In Docker, the default route often belongs to a bridge, so a naive "first address"
or UDP probe returns 172.18.x (container) instead of the host LAN 192.168.x.

Priority:
1. :envvar:`MEETINGBOX_LAN_IP` (or :envvar:`APPLIANCE_LAN_IP`) — set on the host / compose to the
   real LAN (e.g. ``192.168.1.14``).
2. One-line file :envvar:`MEETINGBOX_LAN_IP_FILE` (default ``/data/config/lan_ip``) if present.
3. Heuristic pick from UDP probe, ``hostname -I``, and ``ip -4 addr`` — prefer
   ``192.168/16``, then ``10/8``, deprioritise common Docker ranges ``172.17/16``, ``172.18/16``.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import shutil
import socket
import subprocess
from typing import List

logger = logging.getLogger(__name__)

_FALLBACK = "—"

_INET = re.compile(r"inet (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/", re.MULTILINE)


def _is_rfc1918(ipv4: str) -> bool:
    try:
        ip = ipaddress.IPv4Address(ipv4)
    except (ipaddress.AddressValueError, ValueError):
        return False
    a = int(ip) >> 24
    if a == 10:
        return True
    if 172 <= a <= 31:
        return True
    if a == 192:
        b = (int(ip) >> 16) & 0xFF
        return b == 168
    return False


def _lan_preference_score(ipv4: str) -> int | None:
    """Lower is better. None = skip (loopback, link-local, non-private)."""
    try:
        ip = ipaddress.IPv4Address(ipv4)
    except (ipaddress.AddressValueError, ValueError):
        return None
    if ip.is_loopback or ip.is_link_local:
        return None
    if not _is_rfc1918(str(ip)):
        return 500
    t = (int(ip) >> 16) & 0xFFFF
    a = (int(ip) >> 24) & 0xFF
    # Typical home / office LANs first
    if a == 192 and (int(ip) >> 8) & 0xFF == 168:
        return 0
    if a == 10:
        return 10
    if a == 172:
        b = t & 0xFF
        # docker0, common compose default bridge
        if b == 17:
            return 200
        if b == 18:
            return 150
        if 16 <= b <= 31:
            return 20 + b
    return 40


def _parse_ipv4s_from_text(text: str) -> List[str]:
    if not text:
        return []
    return _INET.findall(text)


def _candidates() -> List[str]:
    out: list[str] = []

    def _add(addr: str) -> None:
        addr = (addr or "").split("%")[0].strip()
        if addr and addr not in out:
            out.append(addr)

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.3)
        try:
            s.connect(("8.8.8.8", 80))
            _add(s.getsockname()[0])
        finally:
            s.close()
    except OSError as e:
        logger.debug("UDP local-IP probe failed: %s", e)

    if shutil.which("hostname"):
        try:
            p = subprocess.run(
                ["hostname", "-I"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            for tok in (p.stdout or "").split():
                _add(tok)
        except (subprocess.SubprocessError, OSError, ValueError) as e:
            logger.debug("hostname -I failed: %s", e)

    if shutil.which("ip"):
        try:
            p = subprocess.run(
                ["ip", "-4", "addr", "show", "up", "scope", "global"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            for a in _parse_ipv4s_from_text(p.stdout or ""):
                _add(a)
        except (subprocess.SubprocessError, OSError, ValueError) as e:
            logger.debug("ip addr failed: %s", e)

    return out


def _read_env_lan() -> str | None:
    for key in ("MEETINGBOX_LAN_IP", "APPLIANCE_LAN_IP"):
        raw = (os.getenv(key) or "").strip()
        if not raw:
            continue
        try:
            ipaddress.IPv4Address(raw.split("%")[0].strip())
        except (ipaddress.AddressValueError, ValueError):
            logger.warning("%s is not a valid IPv4: %r", key, raw)
            continue
        return raw.split("%")[0].strip()
    return None


def _read_lan_file() -> str | None:
    path = (os.getenv("MEETINGBOX_LAN_IP_FILE") or "/data/config/lan_ip").strip()
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            line = f.readline()
    except OSError as e:
        logger.debug("LAN IP file %s not read: %s", path, e)
        return None
    raw = (line or "").split("#", 1)[0].strip()
    if not raw:
        return None
    try:
        ipaddress.IPv4Address(raw.split("%")[0].strip())
    except (ipaddress.AddressValueError, ValueError):
        logger.warning("Invalid IPv4 in %s: %r", path, raw)
        return None
    return raw.split("%")[0].strip()


def get_primary_ipv4() -> str:
    """Return a human-meaningful LAN-style IPv4, or ``"—"`` if unknown.

    For Docker, set ``MEETINGBOX_LAN_IP`` (or a line in ``/data/config/lan_ip``) to
    the host’s address (e.g. ``192.168.1.14``) when auto-detection shows a bridge IP.
    """
    env_ip = _read_env_lan()
    if env_ip:
        return env_ip
    file_ip = _read_lan_file()
    if file_ip:
        return file_ip

    best: tuple[int, str] | None = None
    for c in _candidates():
        sc = _lan_preference_score(c)
        if sc is None:
            continue
        if c.startswith("127."):
            continue
        if best is None or sc < best[0] or (sc == best[0] and c < best[1]):
            best = (sc, c)

    if best is not None:
        return best[1]
    return _FALLBACK
