"""
Wi-Fi probe module to retrieve current Wi-Fi SSID, signal, bitrate, and channel.
Cross-platform support for Linux (nmcli) and Windows (netsh).
"""

import subprocess
import re
import socket
import struct
import platform
from typing import Dict, Any, Optional
import psutil


def get_default_gateway_and_iface() -> tuple[Optional[str], Optional[str]]:
    """
    Find the default network interface and its gateway IP.
    Supports Linux and Windows.
    """
    if platform.system() == "Windows":
        # On Windows, parse 'route print 0.0.0.0' or 'ipconfig'
        try:
            res = subprocess.run(['route', 'print', '0.0.0.0'], capture_output=True, text=True, timeout=2)
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                # Line: 0.0.0.0  0.0.0.0  <gateway>  <interface_ip>  <metric>
                if len(parts) >= 4 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                    gateway = parts[2]
                    ip = parts[3]
                    # Find matching interface name from psutil
                    for name, addrs in psutil.net_if_addrs().items():
                        for addr in addrs:
                            if addr.address == ip:
                                return name, gateway
                    return "Wi-Fi", gateway
        except Exception:
            pass
        return "Wi-Fi", None
    else:
        # Linux: parse /proc/net/route
        try:
            with open('/proc/net/route', 'r') as f:
                for line in f.readlines()[1:]:
                    fields = line.strip().split()
                    if len(fields) >= 4 and fields[1] == '00000000' and (int(fields[3], 16) & 2):
                        iface = fields[0]
                        gw_ip = socket.inet_ntoa(struct.pack('<L', int(fields[2], 16)))
                        return iface, gw_ip
        except Exception:
            pass
        return "wlan0", None


def get_interface_ip(iface: str) -> Optional[str]:
    """Get local IP address of given interface via psutil."""
    try:
        addrs = psutil.net_if_addrs()
        if iface in addrs:
            for addr in addrs[iface]:
                if addr.family == socket.AF_INET:
                    return addr.address
        # Fallback: check all interfaces for a non-loopback IPv4
        for name, addr_list in addrs.items():
            if "lo" in name.lower() or "loopback" in name.lower():
                continue
            for addr in addr_list:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    return addr.address
    except Exception:
        pass
    return None


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

                # Bars approximation
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


def get_wifi_details(iface: str = "wlan0") -> Dict[str, Any]:
    """
    Get Wi-Fi details cross-platform.
    """
    if platform.system() == "Windows":
        details = _get_wifi_details_windows()
        details["interface"] = iface or "Wi-Fi"
    else:
        details = _get_wifi_details_linux(iface)
        details["interface"] = iface

    _, gw = get_default_gateway_and_iface()
    details["gateway_ip"] = gw
    details["local_ip"] = get_interface_ip(details["interface"])
    return details
