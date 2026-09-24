"""
Wi-Fi probe module to retrieve current Wi-Fi SSID, signal, bitrate, and channel.
Cross-platform support for Linux (nmcli) and Windows (netsh).

Optimized with:
- Subprocess caching (gateway, interface IP, and Wi-Fi link status) to minimize CPU usage.
"""

import subprocess
import re
import socket
import struct
import platform
import time
from typing import Dict, Any, Optional
import psutil

# Cache stores to avoid repetitive subprocess execution
_gateway_cache: tuple[Optional[str], Optional[str]] = (None, None)
_gateway_last_check: float = 0.0
_GATEWAY_CACHE_TTL: float = 15.0  # seconds

_ip_cache: Dict[str, tuple[Optional[str], float]] = {}
_IP_CACHE_TTL: float = 10.0  # seconds

_wifi_cache: Optional[Dict[str, Any]] = None
_wifi_last_check: float = 0.0
_WIFI_CACHE_TTL: float = 4.0  # seconds


def get_default_gateway_and_iface(force: bool = False) -> tuple[Optional[str], Optional[str]]:
    """
    Find the default network interface and its gateway IP.
    Supports Linux and Windows with caching to prevent high CPU subprocess churn.
    """
    global _gateway_cache, _gateway_last_check
    now = time.monotonic()
    if not force and _gateway_cache[0] is not None and (now - _gateway_last_check < _GATEWAY_CACHE_TTL):
        return _gateway_cache

    if platform.system() == "Windows":
        try:
            res = subprocess.run(['route', 'print', '0.0.0.0'], capture_output=True, text=True, timeout=2)
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 4 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                    gateway = parts[2]
                    ip = parts[3]
                    for name, addrs in psutil.net_if_addrs().items():
                        for addr in addrs:
                            if addr.address == ip:
                                _gateway_cache = (name, gateway)
                                _gateway_last_check = now
                                return _gateway_cache
                    _gateway_cache = ("Wi-Fi", gateway)
                    _gateway_last_check = now
                    return _gateway_cache
        except Exception:
            pass
        _gateway_cache = ("Wi-Fi", None)
        _gateway_last_check = now
        return _gateway_cache
    else:
        # Linux: fast /proc/net/route parsing (zero subprocesses)
        try:
            with open('/proc/net/route', 'r') as f:
                for line in f.readlines()[1:]:
                    fields = line.strip().split()
                    if len(fields) >= 4 and fields[1] == '00000000' and (int(fields[3], 16) & 2):
                        iface = fields[0]
                        gw_ip = socket.inet_ntoa(struct.pack('<L', int(fields[2], 16)))
                        _gateway_cache = (iface, gw_ip)
                        _gateway_last_check = now
                        return _gateway_cache
        except Exception:
            pass
        _gateway_cache = ("wlan0", None)
        _gateway_last_check = now
        return _gateway_cache


def get_interface_ip(iface: str, force: bool = False) -> Optional[str]:
    """Get local IP address of given interface via psutil (cached for 10s)."""
    global _ip_cache
    now = time.monotonic()
    cached = _ip_cache.get(iface)
    if not force and cached and (now - cached[1] < _IP_CACHE_TTL):
        return cached[0]

    found_ip = None
    try:
        addrs = psutil.net_if_addrs()
        if iface in addrs:
            for addr in addrs[iface]:
                if addr.family == socket.AF_INET:
                    found_ip = addr.address
                    break
        if not found_ip:
            # Fallback: check all interfaces for a non-loopback IPv4
            for name, addr_list in addrs.items():
                if "lo" in name.lower() or "loopback" in name.lower():
                    continue
                for addr in addr_list:
                    if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                        found_ip = addr.address
                        break
                if found_ip:
                    break
    except Exception:
        pass

    _ip_cache[iface] = (found_ip, now)
    return found_ip


def _get_wifi_details_windows() -> Dict[str, Any]:
    """Fetch Wi-Fi information using Windows netsh wlan."""
    info = {
        "connected": False,
        "ssid": "Disconnected",
        "bssid": "N/A",
        "signal": 0,
        "bars": "____",
        "bitrate": "N/A",
        "channel": "N/A",
        "band": "Unknown",
        "security": "N/A",
    }
    try:
        res = subprocess.run(['netsh', 'wlan', 'show', 'interfaces'], capture_output=True, text=True, timeout=2)
        if res.returncode == 0:
            kv = {}
            for line in res.stdout.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    kv[k.strip().lower()] = v.strip()

            state = kv.get("state", "").lower()
            if state == "connected":
                ssid = kv.get("ssid", "Connected")
                bssid = kv.get("bssid", "N/A")
                signal_str = kv.get("signal", "0%").replace("%", "").strip()
                signal = int(signal_str) if signal_str.isdigit() else 0

                rx_rate = kv.get("receive rate (mbps)", "")
                tx_rate = kv.get("transmit rate (mbps)", "")
                bitrate = f"{rx_rate} Mbit/s" if rx_rate else "N/A"
                channel = kv.get("channel", "N/A")
                auth = kv.get("authentication", "N/A")
                radio = kv.get("radio type", "")

                chan_int = int(channel) if channel.isdigit() else 0
                band = "5 GHz" if chan_int >= 36 else ("2.4 GHz" if chan_int > 0 else radio or "Wi-Fi")

                bars = "▂___" if signal < 25 else ("▂▄__" if signal < 50 else ("▂▄▆_" if signal < 75 else "▂▄▆█"))

                info.update({
                    "connected": True,
                    "ssid": ssid,
                    "bssid": bssid,
                    "signal": signal,
                    "bars": bars,
                    "bitrate": bitrate,
                    "channel": channel,
                    "band": band,
                    "security": auth,
                })
    except Exception:
        pass
    return info


def _get_wifi_details_linux(iface: str) -> Dict[str, Any]:
    """Fetch Wi-Fi information using Linux nmcli."""
    info = {
        "connected": False,
        "ssid": "Disconnected",
        "bssid": "N/A",
        "signal": 0,
        "bars": "____",
        "bitrate": "N/A",
        "channel": "N/A",
        "band": "Unknown",
        "security": "N/A",
    }
    try:
        res = subprocess.run(
            ['nmcli', '-t', '-f', 'active,ssid,bssid,signal,bars,rate,chan,security', 'dev', 'wifi'],
            capture_output=True, text=True, timeout=2
        )
        if res.returncode == 0:
            for line in res.stdout.strip().split('\n'):
                if line.startswith('yes:'):
                    clean_line = line.replace(r'\:', '__COLON__')
                    parts = clean_line.split(':')
                    if len(parts) >= 8:
                        ssid = parts[1]
                        bssid = parts[2].replace('__COLON__', ':')
                        signal = int(parts[3]) if parts[3].isdigit() else 0
                        bars = parts[4]
                        rate = parts[5]
                        chan = parts[6]
                        sec = parts[7]

                        chan_int = int(chan) if chan.isdigit() else 0
                        band = "5 GHz" if chan_int >= 36 else ("2.4 GHz" if chan_int > 0 else "Wi-Fi")

                        info.update({
                            "connected": True,
                            "ssid": ssid or "Connected (Hidden)",
                            "bssid": bssid,
                            "signal": signal,
                            "bars": bars,
                            "bitrate": rate,
                            "channel": chan,
                            "band": band,
                            "security": sec,
                        })
                        break
    except Exception:
        pass
    return info


def get_wifi_details(iface: str = "wlan0", force: bool = False) -> Dict[str, Any]:
    """
    Get Wi-Fi details cross-platform with short caching to reduce CPU spikes.
    """
    global _wifi_cache, _wifi_last_check
    now = time.monotonic()
    if not force and _wifi_cache is not None and (now - _wifi_last_check < _WIFI_CACHE_TTL):
        return dict(_wifi_cache)

    if platform.system() == "Windows":
        details = _get_wifi_details_windows()
        details["interface"] = iface or "Wi-Fi"
    else:
        details = _get_wifi_details_linux(iface)
        details["interface"] = iface

    _, gw = get_default_gateway_and_iface()
    details["gateway_ip"] = gw
    details["local_ip"] = get_interface_ip(details["interface"])

    _wifi_cache = details
    _wifi_last_check = now
    return dict(details)
