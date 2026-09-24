"""
Network link diagnostics module.
Detects whether the physical connection is LAN (Ethernet) or WLAN (Wi-Fi),
and retrieves SSID/Link State, bitrate, signal strength, channel/band, and security.

Cross-platform support for Linux (sysfs/nmcli) and Windows (netsh/psutil).
"""

import subprocess
import re
import socket
import struct
import platform
import os
import time
from typing import Dict, Any, Optional
import psutil

from core.platform_utils import run_command_hidden

# Cache stores to avoid repetitive subprocess execution
_gateway_cache: tuple[Optional[str], Optional[str]] = (None, None)
_gateway_last_check: float = 0.0
_GATEWAY_CACHE_TTL: float = 8.0  # seconds

_ip_cache: Dict[str, tuple[Optional[str], float]] = {}
_IP_CACHE_TTL: float = 10.0  # seconds

_net_cache: Optional[Dict[str, Any]] = None
_net_last_check: float = 0.0
_NET_CACHE_TTL: float = 3.0  # seconds


def is_virtual_interface(iface: str) -> bool:
    """Check if an interface is a virtual adapter (TUN, TAP, loopback, docker, etc.)."""
    if not iface:
        return True
    low = iface.lower()
    if low in ("lo", "loopback"):
        return True
    if low.startswith(("br", "docker", "virbr", "veth", "vmnet", "vboxnet", "tun", "tap", "wg", "ppp", "dummy")):
        return True
    for kw in ["tun", "tap", "wg", "wireguard", "sing", "throne", "clash", "ppp",
               "dummy", "docker", "veth", "virbr", "vmnet", "vboxnet", "hyper-v", "wintun",
               "tailscale", "zerotier", "cisco", "anyconnect", "forticlient", "globalprotect",
               "openvpn", "nord", "proton", "mullvad", "surfshark", "warp", "virtual"]:
        if kw in low:
            return True

    if platform.system() != "Windows":
        sys_path = f"/sys/class/net/{iface}"
        if os.path.exists(sys_path) and os.path.islink(sys_path):
            try:
                target = os.readlink(sys_path)
                if "virtual" in target:
                    return True
            except Exception:
                pass
    return False


def is_wireless_interface(iface: str) -> bool:
    """Check if an interface is a wireless (Wi-Fi) adapter."""
    if not iface:
        return False

    low = iface.lower()
    if platform.system() != "Windows":
        sys_path = f"/sys/class/net/{iface}"
        if os.path.exists(os.path.join(sys_path, "wireless")) or os.path.exists(os.path.join(sys_path, "phy80211")):
            return True
        if not os.path.exists(sys_path):
            # Fallback to standard Linux naming conventions (systemd predictable names)
            return low.startswith(("wl", "wlan", "wifi", "ath", "ra"))
        return False
    else:
        return any(k in low for k in ["wi-fi", "wireless", "wlan", "802.11"])


def get_default_gateway_and_iface(force: bool = False) -> tuple[Optional[str], Optional[str]]:
    """
    Find the active default physical network interface and its gateway IP.
    Prioritizes real physical connections (LAN or WLAN) over virtual VPN tunnels.
    """
    global _gateway_cache, _gateway_last_check
    now = time.monotonic()
    if not force and _gateway_cache[0] is not None and (now - _gateway_last_check < _GATEWAY_CACHE_TTL):
        return _gateway_cache

    if platform.system() == "Windows":
        try:
            res = run_command_hidden(['route', 'print', '0.0.0.0'], timeout=2.5)
            candidates = []
            virtual_descs = set()
            in_iface_list = False

            if res.returncode == 0 and res.stdout:
                # 1. Parse Interface List to capture adapter driver descriptions
                for line in res.stdout.splitlines():
                    sline = line.strip()
                    if sline.startswith("Interface List"):
                        in_iface_list = True
                        continue
                    if in_iface_list:
                        if sline.startswith("==="):
                            in_iface_list = False
                            continue
                        if "......" in sline:
                            desc = sline.split("......")[-1].strip().lower()
                            if any(k in desc for k in ["tap", "wintun", "wireguard", "vpn", "virtual", "tunnel",
                                                       "tailscale", "zerotier", "cisco", "anyconnect", "fortinet",
                                                       "palo alto", "hyper-v", "vmware", "virtualbox", "loopback"]):
                                virtual_descs.add(desc)

                # 2. Parse Active Routes for default gateways
                net_addrs = psutil.net_if_addrs()
                for line in res.stdout.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 4 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                        gw = parts[2]
                        ip = parts[3]
                        metric = int(parts[4]) if len(parts) >= 5 and parts[4].isdigit() else 999
                        for name, addrs in net_addrs.items():
                            is_virt = is_virtual_interface(name) or any(vd in name.lower() for vd in virtual_descs)
                            for addr in addrs:
                                if addr.address == ip:
                                    candidates.append({
                                        "name": name,
                                        "gw": gw,
                                        "metric": metric,
                                        "is_virtual": is_virt,
                                        "is_wireless": is_wireless_interface(name)
                                    })
                                    break

            if candidates:
                # Filter for physical network adapters (exclude virtual VPN tunnels)
                phys_candidates = [c for c in candidates if not c["is_virtual"]]
                if not phys_candidates:
                    # If all detected were virtual, pick highest metric (original gateway has higher metric)
                    phys_candidates = sorted(candidates, key=lambda c: c["metric"], reverse=True)

                if phys_candidates:
                    # Sort: prefer Wi-Fi/Ethernet with valid local router gateway (192.168.x / 10.x / 172.x)
                    def _rank_phys(c):
                        gw_ip = c["gw"]
                        is_local_gw = gw_ip.startswith(("192.168.", "10.", "172."))
                        # Higher metric usually belongs to underlying physical route when VPN connects
                        return (1 if is_local_gw else 0, 1 if c["is_wireless"] else 0, c["metric"])

                    phys_candidates.sort(key=_rank_phys, reverse=True)
                    best = phys_candidates[0]
                    _gateway_cache = (best["name"], best["gw"])
                    _gateway_last_check = now
                    return _gateway_cache
        except Exception:
            pass

        # Fallback for Windows: check psutil stats
        try:
            for name, stats in psutil.net_if_stats().items():
                if not is_virtual_interface(name) and stats.isup:
                    _gateway_cache = (name, None)
                    _gateway_last_check = now
                    return _gateway_cache
        except Exception:
            pass

        _gateway_cache = ("Wi-Fi" if is_wireless_interface("Wi-Fi") else "Ethernet", None)
        _gateway_last_check = now
        return _gateway_cache

    else:
        # Linux: Parse /proc/net/route for physical default routes
        found_phys = []
        try:
            with open('/proc/net/route', 'r') as f:
                for line in f.readlines()[1:]:
                    fields = line.strip().split()
                    if len(fields) >= 4 and fields[1] == '00000000' and (int(fields[3], 16) & 2):
                        iface = fields[0]
                        if not is_virtual_interface(iface):
                            gw_ip = socket.inet_ntoa(struct.pack('<L', int(fields[2], 16)))
                            found_phys.append((iface, gw_ip))
        except Exception:
            pass

        if found_phys:
            # If multiple routes, prioritize LAN (Ethernet) over WLAN, or lowest metric
            found_phys.sort(key=lambda item: 0 if not is_wireless_interface(item[0]) else 1)
            _gateway_cache = found_phys[0]
            _gateway_last_check = now
            return _gateway_cache

        # Fallback: find any physical interface with operstate == 'up'
        net_dir = "/sys/class/net"
        if os.path.exists(net_dir):
            try:
                for iface in sorted(os.listdir(net_dir)):
                    if is_virtual_interface(iface):
                        continue
                    oper_file = os.path.join(net_dir, iface, "operstate")
                    if os.path.exists(oper_file):
                        with open(oper_file, "r") as f:
                            if f.read().strip() == "up":
                                _gateway_cache = (iface, None)
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
            for name, addr_list in addrs.items():
                if is_virtual_interface(name):
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


def _get_lan_details_linux(iface: str) -> Dict[str, Any]:
    """Fetch wired Ethernet (LAN) details directly from Linux sysfs."""
    sys_path = f"/sys/class/net/{iface}"
    operstate = "down"
    carrier = "0"
    speed = "N/A"
    duplex = "full"

    if os.path.exists(sys_path):
        try:
            oper_file = os.path.join(sys_path, "operstate")
            if os.path.exists(oper_file):
                with open(oper_file, "r") as f:
                    operstate = f.read().strip().lower()

            carrier_file = os.path.join(sys_path, "carrier")
            if os.path.exists(carrier_file):
                with open(carrier_file, "r") as f:
                    carrier = f.read().strip()

            speed_file = os.path.join(sys_path, "speed")
            if os.path.exists(speed_file):
                with open(speed_file, "r") as f:
                    s = f.read().strip()
                    if s.isdigit():
                        speed = f"{s} Mbit/s"

            duplex_file = os.path.join(sys_path, "duplex")
            if os.path.exists(duplex_file):
                with open(duplex_file, "r") as f:
                    duplex = f.read().strip().lower()
        except Exception:
            pass

    is_connected = operstate == "up" or carrier == "1"
    conn_name = f"Wired Ethernet ({iface})" if is_connected else "Disconnected"
    band_label = f"Ethernet ({duplex.capitalize()} Duplex)" if is_connected else "Ethernet"

    return {
        "connected": is_connected,
        "conn_type": "LAN",
        "type_label": "Ethernet (LAN)",
        "ssid": conn_name,
        "bssid": "N/A",
        "signal": 100 if is_connected else 0,
        "bars": "████" if is_connected else "____",
        "bitrate": speed,
        "channel": "N/A (Cable)",
        "band": band_label,
        "security": "Wired (Physical)" if is_connected else "N/A",
    }


def _get_lan_details_windows(iface: str) -> Dict[str, Any]:
    """Fetch wired Ethernet (LAN) details using psutil on Windows."""
    is_connected = False
    speed = "N/A"
    try:
        stats_dict = psutil.net_if_stats()
        if iface in stats_dict:
            st = stats_dict[iface]
            is_connected = st.isup
            if st.speed > 0:
                speed = f"{st.speed} Mbit/s"
        else:
            for name, st in stats_dict.items():
                if not is_wireless_interface(name) and not is_virtual_interface(name) and st.isup:
                    is_connected = True
                    if st.speed > 0:
                        speed = f"{st.speed} Mbit/s"
                    break
    except Exception:
        pass

    conn_name = "Wired Connection" if is_connected else "Disconnected"
    return {
        "connected": is_connected,
        "conn_type": "LAN",
        "type_label": "Ethernet (LAN)",
        "ssid": conn_name,
        "bssid": "N/A",
        "signal": 100 if is_connected else 0,
        "bars": "████" if is_connected else "____",
        "bitrate": speed,
        "channel": "N/A (Cable)",
        "band": "Ethernet (LAN)",
        "security": "Wired (Physical)" if is_connected else "N/A",
    }


def _get_wifi_details_windows() -> Dict[str, Any]:
    """Fetch Wi-Fi information using Windows netsh wlan."""
    info = {
        "connected": False,
        "conn_type": "WLAN",
        "type_label": "Wi-Fi (WLAN)",
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
        res = run_command_hidden(['netsh', 'wlan', 'show', 'interfaces'], timeout=2.0)
        if res.returncode == 0:
            kv = {}
            for line in res.stdout.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    kv[k.strip().lower()] = v.strip()

            state = kv.get("state", "").lower()
            is_conn = (state == "connected" or "connect" in state or "verbind" in state or
                       ("ssid" in kv and kv["ssid"] and kv["ssid"] != "N/A"))
            if is_conn:
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
        "conn_type": "WLAN",
        "type_label": "Wi-Fi (WLAN)",
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
        res = run_command_hidden(
            ['nmcli', '-t', '-f', 'active,ssid,bssid,signal,bars,rate,chan,security', 'dev', 'wifi'],
            timeout=2.0
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
    Get physical network details (LAN or WLAN) cross-platform.
    Maintains full backward compatibility with all existing wifi keys while adding conn_type.
    """
    global _net_cache, _net_last_check
    now = time.monotonic()
    if not force and _net_cache is not None and (now - _net_last_check < _NET_CACHE_TTL):
        return dict(_net_cache)

    is_windows = platform.system() == "Windows"
    is_wlan = is_wireless_interface(iface)

    if is_wlan:
        details = _get_wifi_details_windows() if is_windows else _get_wifi_details_linux(iface)
    else:
        # Wired LAN interface (eno1, eth0, Ethernet, etc.)
        details = _get_lan_details_windows(iface) if is_windows else _get_lan_details_linux(iface)

    details["interface"] = iface or ("Wi-Fi" if is_wlan else "Ethernet")

    _, gw = get_default_gateway_and_iface()
    details["gateway_ip"] = gw
    details["local_ip"] = get_interface_ip(details["interface"])

    _net_cache = details
    _net_last_check = now
    return dict(details)


# Backwards compatibility alias
get_network_details = get_wifi_details
