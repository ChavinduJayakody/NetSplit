"""
Universal VPN and Proxy Detector.
Supports detecting and monitoring all major proxy & VPN tools and protocols:
- Clients: Throne, NetMod (Syna), Netch, NekoRay, NekoBox, v2rayA, v2rayN, Clash / Mihomo, Hiddify, WireGuard, OpenVPN.
- Protocols: VLESS, VMess, Trojan, Shadowsocks, WireGuard, Hysteria, TUIC, SOCKS5.
- Universal TUN / Wintun / TAP adapter detection on Linux and Windows.
"""

import os
import sys
import platform
import sqlite3
import urllib.request
import json
from typing import Dict, List, Any, Optional
import psutil


KNOWN_PROXY_TOOLS = {
    'throne': ('Throne', 'Sing-Box/Xray Client'),
    'thronecore': ('Throne Core', 'Proxy Core'),
    'netmod': ('NetMod', 'SSH/V2Ray/Xray Client'),
    'syna': ('NetMod Syna', 'VPN/Proxy Client'),
    'netch': ('Netch', 'Bypass & Proxy Client'),
    'nekoray': ('NekoRay', 'V2Ray/Sing-Box Client'),
    'nekobox': ('NekoBox', 'Sing-Box Client'),
    'v2raya': ('v2rayA', 'V2Ray/Xray Web GUI'),
    'v2rayn': ('v2rayN', 'V2Ray/Xray GUI'),
    'clash': ('Clash', 'Rule-based Proxy Core'),
    'mihomo': ('Mihomo / Clash Meta', 'Rule-based Proxy Core'),
    'clash-verge': ('Clash Verge', 'Clash GUI'),
    'sing-box': ('Sing-Box', 'Universal Proxy Core'),
    'xray': ('Xray-core', 'VLESS/VMess/Trojan Core'),
    'v2ray': ('V2Ray-core', 'VMess/VLESS Core'),
    'wv2ray': ('V2Ray Windows', 'VMess/VLESS Core'),
    'hiddify': ('Hiddify', 'Multi-protocol VPN Client'),
    'wireguard': ('WireGuard', 'WireGuard VPN'),
    'wireguard-go': ('WireGuard', 'WireGuard VPN'),
    'openvpn': ('OpenVPN', 'OpenVPN Client'),
    'hysteria': ('Hysteria', 'Hysteria UDP Proxy'),
    'ss-local': ('Shadowsocks', 'Shadowsocks Client'),
    'shadowsocks': ('Shadowsocks', 'Shadowsocks Client'),
    'trojan': ('Trojan', 'Trojan GFW Proxy'),
    'tun2socks': ('tun2socks', 'TUN to SOCKS Forwarder'),
}


def get_throne_candidate_dirs() -> List[str]:
    """Return platform-specific directories where Throne config may reside."""
    candidates = []
    if platform.system() == "Windows":
        for env_var in ["APPDATA", "LOCALAPPDATA", "PROGRAMDATA"]:
            val = os.environ.get(env_var)
            if val:
                candidates.append(os.path.join(val, "Throne", "config"))
        candidates.append(os.path.expanduser(r"~\AppData\Roaming\Throne\config"))
        candidates.append(os.path.expanduser(r"~\AppData\Local\Throne\config"))
    else:
        candidates.append(os.path.expanduser("~/.config/Throne/config"))
        candidates.append(os.path.expanduser("~/.local/share/Throne/config"))
    return candidates


class VpnDetector:
    def __init__(self, custom_iface: Optional[str] = None):
        self.custom_iface = custom_iface
        self.throne_dir = None
        for cand in get_throne_candidate_dirs():
            if os.path.exists(cand):
                self.throne_dir = cand
                break
        if not self.throne_dir:
            self.throne_dir = get_throne_candidate_dirs()[0]

        self.throne_db = os.path.join(self.throne_dir, "throne.db")
        self.throne_stats_db = os.path.join(self.throne_dir, "throne_stats.db")

    def set_custom_interface(self, iface_name: Optional[str]):
        self.custom_iface = iface_name if iface_name and iface_name.strip() else None

    def get_running_clients(self) -> List[Dict[str, str]]:
        """Scan running processes for known VPN and Proxy clients/cores."""
        detected = []
        seen = set()
        try:
            for proc in psutil.process_iter(['name']):
                pname = (proc.info['name'] or '').lower()
                for key, (d_name, desc) in KNOWN_PROXY_TOOLS.items():
                    if key in pname and d_name not in seen:
                        seen.add(d_name)
                        detected.append({
                            "key": key,
                            "name": d_name,
                            "description": desc,
                            "process": proc.info['name']
                        })
        except Exception:
            pass
        return detected

    def is_vpn_running(self) -> bool:
        """Check if any VPN/proxy client or core is running."""
        return len(self.get_running_clients()) > 0

    def get_tun_interface_name(self) -> Optional[str]:
        """
        Universal detection of active TUN, Wintun, or virtual TAP adapter.
        Works across Throne, NetMod, Netch, NekoRay, v2rayA, Clash, Sing-Box, WireGuard, etc.
        """
        active_adapters = list(psutil.net_io_counters(pernic=True).keys())

        # 1. Check custom interface override if configured
        if self.custom_iface and self.custom_iface in active_adapters:
            return self.custom_iface

        # 2. Check Linux kernel /sys/class/net/ for tun_flags or point-to-point virtual devices
        if platform.system() != "Windows":
            net_dir = "/sys/class/net"
            if os.path.exists(net_dir):
                # Prioritize interfaces with tun_flags (true TUN/TAP device)
                for iface in os.listdir(net_dir):
                    if iface in active_adapters:
                        tun_flags_file = os.path.join(net_dir, iface, "tun_flags")
                        if os.path.exists(tun_flags_file):
                            return iface

                # Check virtual link + point-to-point / non-physical
                for iface in os.listdir(net_dir):
                    if iface in ["lo", "eno1", "wlan0", "eth0"]:
                        continue
                    if iface in active_adapters:
                        link = os.path.join(net_dir, iface)
                        if os.path.islink(link) and "virtual" in os.readlink(link):
                            low = iface.lower()
                            if any(k in low for k in ["tun", "tap", "throne", "sing", "nek", "clash", "wg", "meta", "netch", "netmod"]):
                                return iface

        # 3. Windows & Cross-Platform Adapter Name Matcher
        # Known TUN adapter names from Netch, NetMod, Throne, Clash, WireGuard, OpenVPN
        priority_prefixes = [
            "throne", "wintun", "sing-box", "clash", "nekoray", "nekobox",
            "netch", "netmod", "wireguard", "wg", "tun", "tap"
        ]

        for p in priority_prefixes:
            for adapter in active_adapters:
                low = adapter.lower()
                if low.startswith(p) or (p in low and "tunnel" not in low):
                    return adapter

        return None

    def is_tun_active(self) -> bool:
        """Check if any TUN/VPN adapter is currently active."""
        return self.get_tun_interface_name() is not None

    def get_active_profile_and_protocol(self) -> tuple[Optional[str], Optional[str]]:
        """
        Detect active profile name and protocol (VLESS, VMess, Trojan, etc.).
        """
        # 1. Check Throne SQLite Database if available
        if os.path.exists(self.throne_db):
            try:
                uri = f"file:{self.throne_db}?mode=ro"
                with sqlite3.connect(uri, uri=True, timeout=1.0) as conn:
                    c = conn.cursor()
                    c.execute("SELECT name, type FROM profiles LIMIT 1;")
                    row = c.fetchone()
                    if row:
                        proto = (row[1] or "VPN").upper()
                        return row[0], proto
            except Exception:
                pass

        # 2. Check Clash / Mihomo REST API if active
        for port in [9090, 9097, 2080]:
            try:
                url = f"http://127.0.0.1:{port}/proxies"
                req = urllib.request.Request(url, headers={'User-Agent': 'NetSplit'})
                with urllib.request.urlopen(req, timeout=0.3) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    if "proxies" in data:
                        return "Clash / Mihomo", "Rule-Based"
            except Exception:
                pass

        # 3. Detect from running client names
        running = self.get_running_clients()
        if running:
            primary = running[0]
            name = primary["name"]
            if "netmod" in primary["key"]:
                return "NetMod Active", "SSH/V2Ray"
            elif "netch" in primary["key"]:
                return "Netch Active", "Bypass/TUN"
            elif "nekoray" in primary["key"] or "nekobox" in primary["key"]:
                return primary["name"], "Sing-Box/Xray"
            elif "xray" in primary["key"] or "v2ray" in primary["key"]:
                return primary["name"], "VLESS/VMess"
            elif "clash" in primary["key"] or "mihomo" in primary["key"]:
                return primary["name"], "Rule-Based"
            elif "wireguard" in primary["key"]:
                return "WireGuard", "WireGuard"
            elif "openvpn" in primary["key"]:
                return "OpenVPN", "OpenVPN"
            return name, "VPN/Proxy"

        return None, None

    def get_top_apps(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve top applications from Throne stats DB if available."""
        if not os.path.exists(self.throne_stats_db):
            return []

        apps = []
        try:
            uri = f"file:{self.throne_stats_db}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=1.0) as conn:
                c = conn.cursor()
                query = """
                    SELECT process_name, SUM(up) as total_up, SUM(down) as total_down
                    FROM app_traffic_minute
                    GROUP BY process_name
                    ORDER BY (total_up + total_down) DESC
                    LIMIT ?
                """
                c.execute(query, (limit,))
                for row in c.fetchall():
                    proc_name, up_bytes, down_bytes = row[0], row[1] or 0, row[2] or 0
                    total = up_bytes + down_bytes
                    apps.append({
                        "process": proc_name,
                        "up_bytes": up_bytes,
                        "down_bytes": down_bytes,
                        "total_bytes": total
                    })
        except Exception:
            pass
        return apps

    def get_status_summary(self) -> Dict[str, Any]:
        """Comprehensive summary of active VPN / Proxy status."""
        running_tools = self.get_running_clients()
        is_running = len(running_tools) > 0
        tun_active = self.is_tun_active()
        tun_name = self.get_tun_interface_name()
        profile_name, protocol = self.get_active_profile_and_protocol()

        primary_client = running_tools[0]["name"] if running_tools else "VPN / Proxy"

        status_text = "Disconnected"
        if tun_active:
            if profile_name and protocol:
                status_text = f"Connected: {protocol} ({profile_name})"
            elif profile_name:
                status_text = f"Connected ({profile_name})"
            else:
                status_text = f"Connected ({primary_client} TUN)"
        elif is_running:
            status_text = f"Running ({primary_client} Standby)"

        return {
            "is_running": is_running,
            "tun_active": tun_active,
            "tun_interface": tun_name,
            "status_text": status_text,
            "client_name": primary_client,
            "active_profile": profile_name or (primary_client if is_running else "None"),
            "profile_type": protocol or "VPN/Proxy",
            "running_tools": running_tools,
            "top_apps": self.get_top_apps(limit=8),
        }
