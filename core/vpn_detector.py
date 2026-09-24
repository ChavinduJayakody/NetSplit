"""
Universal VPN and Proxy Detector.
Supports detecting and monitoring all major proxy & VPN tools and protocols:
- Clients: Throne, NetMod (Syna), Netch, NekoRay, NekoBox, v2rayA, v2rayN, Clash / Mihomo, Hiddify, WireGuard, OpenVPN.
- Protocols: VLESS, VMess, Trojan, Shadowsocks, WireGuard, Hysteria, TUIC, SOCKS5.
- Universal TUN / Wintun / TAP adapter detection on Linux and Windows.

Optimized with:
- Intelligent TTL caching on process scans to prevent burning CPU in psutil.process_iter()
- Adapter name passing to avoid duplicate net_io_counters() calls
- Conditional REST API probing for Clash/Mihomo (only probed when tool is running)
"""

import os
import sys
import platform
import sqlite3
import urllib.request
import json
import time
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

        # Caching mechanisms to reduce CPU usage
        self._cached_clients: List[Dict[str, str]] = []
        self._last_clients_check: float = 0.0
        self._clients_cache_ttl: float = 3.0  # seconds

        self._cached_tun: Optional[str] = None
        self._last_tun_check: float = 0.0
        self._tun_cache_ttl: float = 2.0  # seconds

        self._cached_summary: Optional[Dict[str, Any]] = None
        self._last_summary_check: float = 0.0
        self._summary_cache_ttl: float = 1.0  # seconds

    def set_custom_interface(self, iface_name: Optional[str]):
        self.custom_iface = iface_name if iface_name and iface_name.strip() else None
        self._cached_tun = None

    def get_running_clients(self, force: bool = False) -> List[Dict[str, str]]:
        """Scan running processes for known VPN and Proxy clients/cores (cached)."""
        now = time.monotonic()
        if not force and (now - self._last_clients_check < self._clients_cache_ttl):
            return list(self._cached_clients)

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

        self._cached_clients = detected
        self._last_clients_check = now
        return detected

    def is_vpn_running(self) -> bool:
        """Check if any VPN/proxy client or core is running."""
        return len(self.get_running_clients()) > 0

    def get_tun_interface_name(self, active_adapters: Optional[List[str]] = None) -> Optional[str]:
        """
        Universal detection of active TUN, Wintun, or virtual TAP adapter.
        Works across Throne, NetMod, Netch, NekoRay, v2rayA, Clash, Sing-Box, WireGuard, etc.
        """
        now = time.monotonic()

        if active_adapters is None:
            active_adapters = list(psutil.net_io_counters(pernic=True).keys())

        # If previously detected TUN is still active in adapters, reuse it
        if self._cached_tun and self._cached_tun in active_adapters and (now - self._last_tun_check < self._tun_cache_ttl):
            return self._cached_tun

        self._last_tun_check = now

        # 1. Check custom interface override if configured
        if self.custom_iface and self.custom_iface in active_adapters:
            self._cached_tun = self.custom_iface
            return self.custom_iface

        # 2. Check Linux kernel /sys/class/net/ for tun_flags or point-to-point virtual devices
        if platform.system() != "Windows":
            net_dir = "/sys/class/net"
            if os.path.exists(net_dir):
                try:
                    all_sys_ifaces = os.listdir(net_dir)
                    # Prioritize interfaces with tun_flags (true TUN/TAP device)
                    for iface in all_sys_ifaces:
                        if iface in active_adapters:
                            tun_flags_file = os.path.join(net_dir, iface, "tun_flags")
                            if os.path.exists(tun_flags_file):
                                self._cached_tun = iface
                                return iface

                    # Check virtual link + point-to-point / non-physical
                    for iface in all_sys_ifaces:
                        if iface in ["lo", "eno1", "wlan0", "eth0"]:
                            continue
                        if iface in active_adapters:
                            link = os.path.join(net_dir, iface)
                            if os.path.islink(link) and "virtual" in os.readlink(link):
                                low = iface.lower()
                                if any(k in low for k in ["tun", "tap", "throne", "sing", "nek", "clash", "wg", "meta", "netch", "netmod"]):
                                    self._cached_tun = iface
                                    return iface
                except Exception:
                    pass

        # 3. Windows & Cross-Platform Adapter Name Matcher
        priority_prefixes = [
            "throne", "wintun", "sing-box", "clash", "nekoray", "nekobox",
            "netch", "netmod", "wireguard", "wg", "tun", "tap"
        ]

        for p in priority_prefixes:
            for adapter in active_adapters:
                low = adapter.lower()
                if low.startswith(p) or (p in low and "tunnel" not in low):
                    self._cached_tun = adapter
                    return adapter

        self._cached_tun = None
        return None

    def is_tun_active(self) -> bool:
        """Check if any TUN/VPN adapter is currently active."""
        return self.get_tun_interface_name() is not None

    def get_active_profile_and_protocol(self, running_clients: Optional[List[Dict[str, str]]] = None) -> tuple[Optional[str], Optional[str]]:
        """
        Detect active profile name and protocol (VLESS, VMess, Trojan, etc.).
        """
        # 1. Check Throne SQLite Database if available
        if os.path.exists(self.throne_db):
            try:
                uri = f"file:{self.throne_db}?mode=ro"
                conn = sqlite3.connect(uri, uri=True, timeout=1.0)
                try:
                    c = conn.cursor()
                    c.execute("SELECT name, type FROM profiles LIMIT 1;")
                    row = c.fetchone()
                    if row:
                        proto = (row[1] or "VPN").upper()
                        return row[0], proto
                finally:
                    conn.close()
            except Exception:
                pass

        if running_clients is None:
            running_clients = self.get_running_clients()

        # 2. Check Clash / Mihomo REST API if running
        is_clash_running = any('clash' in c['key'] or 'mihomo' in c['key'] for c in running_clients)
        if is_clash_running:
            for port in [9090, 9097, 2080]:
                try:
                    url = f"http://127.0.0.1:{port}/proxies"
                    req = urllib.request.Request(url, headers={'User-Agent': 'NetSplit'})
                    with urllib.request.urlopen(req, timeout=0.2) as resp:
                        data = json.loads(resp.read().decode('utf-8'))
                        if "proxies" in data:
                            return "Clash / Mihomo", "Rule-Based"
                except Exception:
                    pass

        # 3. Detect from running client names
        if running_clients:
            primary = running_clients[0]
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
            conn = sqlite3.connect(uri, uri=True, timeout=1.0)
            try:
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
            finally:
                conn.close()
        except Exception:
            pass
        return apps

    def get_status_summary(self, active_adapters: Optional[List[str]] = None) -> Dict[str, Any]:
        """Comprehensive summary of active VPN / Proxy status (with 1.0s caching)."""
        now = time.monotonic()
        if self._cached_summary and (now - self._last_summary_check < self._summary_cache_ttl):
            return dict(self._cached_summary)

        running_tools = self.get_running_clients()
        is_running = len(running_tools) > 0
        tun_name = self.get_tun_interface_name(active_adapters=active_adapters)
        tun_active = tun_name is not None
        profile_name, protocol = self.get_active_profile_and_protocol(running_clients=running_tools)

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

        summary = {
            "is_running": is_running,
            "tun_active": tun_active,
            "tun_interface": tun_name,
            "status_text": status_text,
            "client_name": primary_client,
            "active_profile": profile_name or (primary_client if is_running else "None"),
            "profile_type": protocol or "VPN/Proxy",
            "running_tools": running_tools,
            # Only report per-app stats when a TUN is actually up
            "top_apps": self.get_top_apps(limit=8) if tun_active else [],
        }

        self._cached_summary = summary
        self._last_summary_check = now
        return summary
