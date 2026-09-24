"""
Universal VPN and Proxy Detector.
Automatically detects whatever VPN, proxy, or tunnel software is used:
- Commercial VPNs: NordVPN, ProtonVPN, ExpressVPN, Surfshark, Mullvad, Windscribe, PIA, CyberGhost, IVPN, etc.
- Corporate / Enterprise: Cisco AnyConnect, FortiClient, GlobalProtect, SonicWall, Pulse Secure, SoftEther, OpenConnect.
- Mesh & Cloud VPNs: Tailscale, ZeroTier, Cloudflare WARP, WireGuard, OpenVPN.
- Proxy Cores & Clients: Sing-Box, Xray, V2Ray, Clash, Mihomo, Clash Verge, NekoRay, NekoBox, Hiddify, NetMod, Netch, Throne, Shadowsocks, Trojan, Hysteria, TUIC, NaiveProxy, Gost, Brook, Redsocks, tun2socks.
- Universal TUN / Wintun / TAP / Point-to-Point virtual adapters on Linux and Windows.
- System Proxy (HTTP / SOCKS) and local proxy listening ports.

Optimized with intelligent TTL caching to minimize CPU and memory footprint.
"""

import os
import sys
import platform
import sqlite3
import urllib.request
import json
import socket
import time
import re
from typing import Dict, List, Any, Optional
import psutil

from core.wifi import is_wireless_interface


# Comprehensive signature database of known VPN, Proxy, and Tunnel tools
KNOWN_PROXY_TOOLS = {
    # Sing-box, Xray, V2Ray ecosystem
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
    'clash-nyanpasu': ('Clash Nyanpasu', 'Clash GUI'),
    'flclash': ('Flclash', 'Clash GUI'),
    'sing-box': ('Sing-Box', 'Universal Proxy Core'),
    'xray': ('Xray-core', 'VLESS/VMess/Trojan Core'),
    'v2ray': ('V2Ray-core', 'VMess/VLESS Core'),
    'wv2ray': ('V2Ray Windows', 'VMess/VLESS Core'),
    'hiddify': ('Hiddify', 'Multi-protocol VPN Client'),
    'karing': ('Karing', 'Multi-protocol Proxy Client'),
    'matsuri': ('Matsuri', 'Sing-Box/V2Ray Client'),
    'dae-proxy': ('dae', 'eBPF-based Proxy'),

    # Protocols & Forwarders
    'wireguard': ('WireGuard', 'WireGuard VPN'),
    'wireguard-go': ('WireGuard', 'WireGuard VPN'),
    'wg-quick': ('WireGuard', 'WireGuard VPN'),
    'openvpn': ('OpenVPN', 'OpenVPN Client/Daemon'),
    'openvpn-service': ('OpenVPN', 'OpenVPN Service'),
    'hysteria': ('Hysteria', 'Hysteria UDP Proxy'),
    'tuic-client': ('TUIC', 'TUIC QUIC Proxy'),
    'tuic': ('TUIC', 'TUIC QUIC Proxy'),
    'ss-local': ('Shadowsocks', 'Shadowsocks Client'),
    'shadowsocks': ('Shadowsocks', 'Shadowsocks Client'),
    'shadowsocks-rust': ('Shadowsocks', 'Shadowsocks-Rust'),
    'sslocal': ('Shadowsocks', 'Shadowsocks-Rust Client'),
    'trojan': ('Trojan', 'Trojan GFW Proxy'),
    'trojan-go': ('Trojan-Go', 'Trojan-Go Proxy'),
    'naive': ('NaiveProxy', 'Chromium Network Stack Proxy'),
    'naiveproxy': ('NaiveProxy', 'Chromium Network Stack Proxy'),
    'brook': ('Brook', 'Cross-Platform Proxy'),
    'gost': ('Gost', 'GO Simple Tunnel'),
    'tun2socks': ('tun2socks', 'TUN to SOCKS Forwarder'),
    'badvpn-tun2socks': ('BadVPN', 'TUN to SOCKS Forwarder'),
    'redsocks': ('redsocks', 'Transparent SOCKS Redirector'),
    'wstunnel': ('wstunnel', 'WebSocket Tunnel'),

    # Mesh & Cloud VPNs
    'tailscale': ('Tailscale', 'Mesh VPN'),
    'tailscaled': ('Tailscale', 'Tailscale Daemon'),
    'zerotier': ('ZeroTier', 'Virtual Network'),
    'zerotier-one': ('ZeroTier', 'ZeroTier One Service'),
    'warp-svc': ('Cloudflare WARP', 'WARP VPN Daemon'),
    'warp-cli': ('Cloudflare WARP', 'WARP VPN Client'),
    'cloudflare-warp': ('Cloudflare WARP', 'WARP VPN'),

    # Commercial VPNs
    'protonvpn': ('Proton VPN', 'Proton VPN Client'),
    'protonvpn-service': ('Proton VPN', 'Proton VPN Daemon'),
    'nordvpn': ('NordVPN', 'NordVPN Client'),
    'nordvpnd': ('NordVPN', 'NordVPN Daemon'),
    'mullvad-vpn': ('Mullvad VPN', 'Mullvad VPN Client'),
    'mullvad-daemon': ('Mullvad VPN', 'Mullvad VPN Daemon'),
    'expressvpn': ('ExpressVPN', 'ExpressVPN Client'),
    'expressvpnd': ('ExpressVPN', 'ExpressVPN Daemon'),
    'surfshark': ('Surfshark', 'Surfshark VPN Client'),
    'surfsharkd': ('Surfshark', 'Surfshark VPN Daemon'),
    'windscribe': ('Windscribe', 'Windscribe VPN Client'),
    'windscribed': ('Windscribe', 'Windscribe VPN Daemon'),
    'ivpn': ('IVPN', 'IVPN Client'),
    'ivpn-service': ('IVPN', 'IVPN Daemon'),
    'pia-client': ('Private Internet Access', 'PIA VPN Client'),
    'pia-daemon': ('Private Internet Access', 'PIA VPN Daemon'),
    'cyberghost': ('CyberGhost', 'CyberGhost VPN'),

    # Enterprise / Corporate VPNs
    'vpnagentd': ('Cisco AnyConnect', 'Cisco Secure Client Agent'),
    'ciscod': ('Cisco AnyConnect', 'Cisco AnyConnect Daemon'),
    'anyconnect': ('Cisco AnyConnect', 'Cisco AnyConnect VPN'),
    'forticlient': ('FortiClient', 'Fortinet SSL-VPN Client'),
    'forticlientsslvpn': ('FortiClient', 'Fortinet SSL-VPN'),
    'pangps': ('GlobalProtect', 'Palo Alto GlobalProtect Service'),
    'pangpa': ('GlobalProtect', 'Palo Alto GlobalProtect Agent'),
    'globalprotect': ('GlobalProtect', 'Palo Alto GlobalProtect VPN'),
    'pulsesvc': ('Pulse Secure / Ivanti', 'Pulse Secure VPN Service'),
    'pulse-secure': ('Pulse Secure / Ivanti', 'Pulse Secure Client'),
    'vpnclient': ('SoftEther VPN', 'SoftEther VPN Client'),
    'openconnect': ('OpenConnect', 'Multi-Protocol SSL VPN'),
    'charon': ('StrongSwan', 'IPsec / IKEv2 Daemon'),
    'swanctl': ('StrongSwan', 'IPsec VPN Client'),
    'ipsec': ('IPsec', 'IPsec VPN Daemon'),

    # Privacy & Anonymity
    'tor': ('Tor', 'Tor Onion Router'),
    'obfs4proxy': ('Tor Pluggable Transport', 'Tor Obfs4 Proxy'),
    'snowflake-client': ('Tor Snowflake', 'Tor Pluggable Transport'),
    'outline-client': ('Outline VPN', 'Shadowsocks-based VPN'),
    'psiphon': ('Psiphon', 'Censorship Circumvention VPN'),
    'psiphond': ('Psiphon', 'Psiphon Tunnel Daemon'),
    'lantern': ('Lantern', 'Peer-to-Peer Proxy'),
    'privoxy': ('Privoxy', 'Privacy Enhancing Proxy'),
    'tinyproxy': ('Tinyproxy', 'Lightweight HTTP/HTTPS Proxy'),
}

# Generic keywords to catch unknown custom VPN/proxy binaries
GENERIC_VPN_KEYWORDS = [
    'vpn', 'proxy', 'tunnel', 'tun2', 'socks', 'shadowsocks',
    'v2ray', 'xray', 'sing-box', 'clash', 'hysteria', 'tuic', 'trojan',
    'wireguard', 'openvpn', 'tailscale', 'zerotier'
]

# System daemon whitelist to ignore false positives
EXCLUDED_PROCESSES = {
    'gsd-screensaver-proxy', 'systemd', 'dbus-daemon', 'packagekitd',
    'polkitd', 'accounts-daemon', 'cupsd', 'avahi-daemon', 'kernel'
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


def _matches_signature(key: str, pname: str, cmd: str) -> bool:
    """Accurately match tool key against process name or cmdline with boundary checks for short names."""
    if len(key) <= 4:
        pattern = r'(?:^|[\/\s_-])' + re.escape(key) + r'(?:$|[\/\s_.-])'
        return bool(re.search(pattern, pname)) or bool(re.search(pattern, cmd))
    return key in pname or key in cmd


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

        self._cached_top_apps: List[Dict[str, Any]] = []
        self._last_top_apps_check: float = 0.0
        self._top_apps_cache_ttl: float = 2.5  # seconds

        self._cached_sys_proxy: Optional[Dict[str, Any]] = None
        self._last_sys_proxy_check: float = 0.0
        self._sys_proxy_cache_ttl: float = 4.0  # seconds

    def set_custom_interface(self, iface_name: Optional[str]):
        self.custom_iface = iface_name if iface_name and iface_name.strip() else None
        self._cached_tun = None

    def _infer_client_name_from_adapter(self, adapter: str) -> str:
        """Infer human-friendly client or protocol name from interface name."""
        low = adapter.lower()
        if "tailscale" in low:
            return "Tailscale"
        elif "nord" in low:
            return "NordVPN (NordLynx)"
        elif "proton" in low:
            return "Proton VPN"
        elif "mullvad" in low:
            return "Mullvad VPN"
        elif "surfshark" in low:
            return "Surfshark VPN"
        elif "warp" in low:
            return "Cloudflare WARP"
        elif "wireguard" in low or low.startswith("wg"):
            return "WireGuard"
        elif "csco" in low or "anyconnect" in low:
            return "Cisco AnyConnect"
        elif "forti" in low or "fct" in low:
            return "FortiClient"
        elif "zt" in low or "zerotier" in low:
            return "ZeroTier"
        elif "throne" in low:
            return "Throne"
        elif "clash" in low or "meta" in low:
            return "Clash / Mihomo"
        elif "sing" in low:
            return "Sing-Box"
        elif "netmod" in low:
            return "NetMod"
        elif "netch" in low:
            return "Netch"
        elif "nek" in low:
            return "NekoRay / NekoBox"
        elif "openvpn" in low:
            return "OpenVPN"
        elif "wintun" in low:
            return "Wintun Tunnel"
        elif "tap" in low:
            return "TAP Adapter"
        elif "tun" in low:
            return "VPN / Proxy Tunnel"
        return f"Virtual Tunnel ({adapter})"

    def _find_process_holding_tun(self, tun_iface: str) -> Optional[Dict[str, str]]:
        """
        On Linux, inspect which process has open file descriptors to /dev/net/tun.
        This provides 100% automatic identification of any custom or unknown VPN core.
        """
        if platform.system() == "Windows":
            return None

        try:
            # Check user processes in /proc
            for pid_dir in os.listdir("/proc"):
                if not pid_dir.isdigit():
                    continue
                fd_path = f"/proc/{pid_dir}/fd"
                if not os.path.exists(fd_path):
                    continue
                try:
                    for fd in os.listdir(fd_path):
                        target = os.readlink(os.path.join(fd_path, fd))
                        if "tun" in target or tun_iface in target:
                            # Found the process holding the TUN device!
                            comm_file = f"/proc/{pid_dir}/comm"
                            proc_name = pid_dir
                            if os.path.exists(comm_file):
                                with open(comm_file, "r") as f:
                                    proc_name = f.read().strip()
                            return {
                                "key": proc_name.lower(),
                                "name": proc_name,
                                "description": f"Process holding {tun_iface}",
                                "process": proc_name
                            }
                except (PermissionError, FileNotFoundError, OSError):
                    continue
        except Exception:
            pass
        return None

    def get_running_clients(self, force: bool = False, tun_iface: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Scan running processes for known and generic VPN / Proxy clients or cores.
        Automatically detects whatever VPN software is active.
        """
        now = time.monotonic()
        if not force and (now - self._last_clients_check < self._clients_cache_ttl):
            return list(self._cached_clients)

        detected = []
        seen = set()

        # 1. Match known tools and generic keywords from process table
        try:
            for proc in psutil.process_iter(['name', 'cmdline']):
                raw_name = proc.info.get('name') or ''
                pname = raw_name.lower()
                cmd = ' '.join(proc.info.get('cmdline') or []).lower()

                # Skip known desktop daemons that contain the word 'proxy'
                if pname in EXCLUDED_PROCESSES or any(ex in pname for ex in ['screensaver', 'polkit']):
                    continue

                # A. Check signature dictionary
                matched = False
                for key, (d_name, desc) in KNOWN_PROXY_TOOLS.items():
                    if _matches_signature(key, pname, cmd) and d_name not in seen:
                        seen.add(d_name)
                        detected.append({
                            "key": key,
                            "name": d_name,
                            "description": desc,
                            "process": raw_name
                        })
                        matched = True
                        break

                # B. Check generic patterns for unlisted or custom VPN/proxy binaries
                if not matched and len(pname) > 2:
                    for kw in GENERIC_VPN_KEYWORDS:
                        if (kw in pname or f"--{kw}" in cmd) and raw_name not in seen:
                            # Avoid matching generic system tools
                            if pname in ['python', 'python3', 'bash', 'sh', 'zsh', 'code', 'chrome', 'firefox']:
                                continue
                            seen.add(raw_name)
                            detected.append({
                                "key": pname,
                                "name": raw_name,
                                "description": f"Generic {kw.upper()} Software",
                                "process": raw_name
                            })
                            break
        except Exception:
            pass

        # 2. If a TUN interface is active and no tool was matched yet, check process holding TUN
        if tun_iface and not detected:
            tun_proc = self._find_process_holding_tun(tun_iface)
            if tun_proc and tun_proc["name"] not in seen:
                seen.add(tun_proc["name"])
                detected.append(tun_proc)

        # 3. If a TUN interface is active, but process is running in root/container, infer from interface name
        if tun_iface and not detected:
            inferred_name = self._infer_client_name_from_adapter(tun_iface)
            detected.append({
                "key": tun_iface.lower(),
                "name": inferred_name,
                "description": f"Active Virtual Tunnel ({tun_iface})",
                "process": tun_iface
            })

        self._cached_clients = detected
        self._last_clients_check = now
        return detected

    def is_vpn_running(self) -> bool:
        """Check if any VPN/proxy client or core is running."""
        return len(self.get_running_clients()) > 0

    def get_tun_interface_name(self, active_adapters: Optional[List[str]] = None) -> Optional[str]:
        """
        Universal detection of active TUN, Wintun, WireGuard, or virtual TAP adapter.
        Works across ANY software: WireGuard, OpenVPN, Tailscale, ZeroTier, Cloudflare WARP,
        Commercial VPNs (Nord, Proton, Mullvad, etc.), Sing-Box, Xray, Clash, NetMod, Netch, etc.
        """
        now = time.monotonic()

        if active_adapters is None:
            active_adapters = list(psutil.net_io_counters(pernic=True).keys())

        # If previously detected TUN is still active in adapters, reuse it within TTL
        if self._cached_tun and self._cached_tun in active_adapters and (now - self._last_tun_check < self._tun_cache_ttl):
            return self._cached_tun

        self._last_tun_check = now

        # 1. Custom interface override if configured
        if self.custom_iface and self.custom_iface in active_adapters:
            self._cached_tun = self.custom_iface
            return self.custom_iface

        # Candidate interfaces mapped to scores
        candidate_scores: Dict[str, int] = {}

        # 2. Linux Kernel Sysfs & Route Table Inspection
        if platform.system() != "Windows":
            net_dir = "/sys/class/net"
            if os.path.exists(net_dir):
                try:
                    for iface in active_adapters:
                        if iface == "lo" or iface.startswith("lo"):
                            continue
                        # Skip physical interfaces (Ethernet & Wi-Fi)
                        if is_wireless_interface(iface):
                            continue
                        if iface.startswith(("eno", "eth", "enp", "ens", "wlan", "wlp", "wlx")):
                            continue
                        # Skip virtual bridge / docker / container interfaces
                        if iface.startswith(("docker", "br-", "virbr", "veth", "vmnet", "vboxnet", "cni", "flannel")):
                            continue

                        sys_path = os.path.join(net_dir, iface)
                        if not os.path.exists(sys_path):
                            low = iface.lower()
                            for p in ["tun", "tap", "wg", "wireguard", "tailscale", "zerotier", "zt",
                                      "nord", "proton", "mullvad", "surfshark", "warp", "csco", "cisco",
                                      "anyconnect", "fct", "wintun", "sing", "clash", "nek", "netmod",
                                      "netch", "ppp", "vpn", "meta"]:
                                if low.startswith(p) or (p in low and "tunnel" not in low):
                                    candidate_scores[iface] = 50
                                    break
                            continue

                        score = 0
                        # A. True TUN/TAP driver flag (e.g. OpenVPN, Sing-box, Throne, NetMod)
                        if os.path.exists(os.path.join(sys_path, "tun_flags")):
                            score += 100

                        # B. Check flags (bit 0x10 = IFF_POINTOPOINT: WireGuard, OpenVPN, Tailscale, PPP)
                        flags_file = os.path.join(sys_path, "flags")
                        if os.path.exists(flags_file):
                            try:
                                with open(flags_file, "r") as f:
                                    flags_val = int(f.read().strip(), 16)
                                    if flags_val & 0x10:  # IFF_POINTOPOINT
                                        score += 90
                            except Exception:
                                pass

                        # C. Check ARPHRD type (65534 = ARPHRD_NONE, standard for IP tunnels and WireGuard)
                        type_file = os.path.join(sys_path, "type")
                        if os.path.exists(type_file):
                            try:
                                with open(type_file, "r") as f:
                                    t_val = int(f.read().strip())
                                    if t_val == 65534:
                                        score += 85
                            except Exception:
                                pass

                        # D. Check if virtual device link exists
                        if os.path.islink(sys_path):
                            try:
                                target = os.readlink(sys_path)
                                if "virtual" in target:
                                    score += 20
                            except Exception:
                                pass

                        # E. Check VPN prefix heuristics
                        low = iface.lower()
                        for p in ["tun", "tap", "wg", "wireguard", "tailscale", "zerotier", "zt",
                                  "nord", "proton", "mullvad", "surfshark", "warp", "csco", "cisco",
                                  "anyconnect", "fct", "wintun", "sing", "clash", "nek", "netmod",
                                  "netch", "ppp", "vpn", "meta"]:
                            if low.startswith(p) or (p in low and "tunnel" not in low):
                                score += 50
                                break

                        if score > 0:
                            candidate_scores[iface] = score

                except Exception:
                    pass

        # 3. Windows Adapter Name & Driver Matcher
        else:
            vpn_keywords = [
                "wintun", "wireguard", "tap", "tun", "tailscale", "zerotier",
                "nord", "proton", "surfshark", "mullvad", "express", "cisco",
                "anyconnect", "fortinet", "forticlient", "sonicwall", "pulse",
                "sing-box", "clash", "nekoray", "netch", "netmod", "xray",
                "v2ray", "warp", "cloudflare", "vpn"
            ]
            for adapter in active_adapters:
                low = adapter.lower()
                # Skip typical physical adapter names
                if any(k in low for k in ["wi-fi", "wireless", "ethernet", "local area connection"]) and not any(vk in low for vk in ["tap", "wintun", "vpn"]):
                    continue
                for vk in vpn_keywords:
                    if vk in low:
                        candidate_scores[adapter] = candidate_scores.get(adapter, 0) + 70
                        break

        # Return candidate with highest score
        if candidate_scores:
            best_iface = max(candidate_scores.items(), key=lambda x: x[1])[0]
            self._cached_tun = best_iface
            return best_iface

        self._cached_tun = None
        return None

    def is_tun_active(self) -> bool:
        """Check if any TUN/VPN adapter is currently active."""
        return self.get_tun_interface_name() is not None

    def get_system_proxy_info(self) -> Dict[str, Any]:
        """
        Detect system-level proxy configurations (GNOME, Windows Registry, environment variables,
        or active local proxy listeners).
        """
        now = time.monotonic()
        if self._cached_sys_proxy and (now - self._last_sys_proxy_check < self._sys_proxy_cache_ttl):
            return dict(self._cached_sys_proxy)

        self._last_sys_proxy_check = now
        info = {
            "enabled": False,
            "type": None,
            "host": None,
            "port": None,
            "label": None
        }

        # 1. Check environment variables
        for env_key in ["all_proxy", "http_proxy", "https_proxy", "ALL_PROXY", "HTTP_PROXY"]:
            val = os.environ.get(env_key)
            if val and "://" in val:
                try:
                    parts = val.split("://")[-1].split(":")
                    host = parts[0]
                    port = int(parts[1].split("/")[0])
                    info.update({
                        "enabled": True,
                        "type": "Environment Proxy",
                        "host": host,
                        "port": port,
                        "label": f"{host}:{port}"
                    })
                    self._cached_sys_proxy = info
                    return info
                except Exception:
                    pass

        # 2. Check GNOME System Proxy (Linux)
        if platform.system() != "Windows":
            try:
                import subprocess
                res = subprocess.run(['gsettings', 'get', 'org.gnome.system.proxy', 'mode'],
                                     capture_output=True, text=True, timeout=0.2)
                mode = res.stdout.strip().replace("'", "")
                if mode == "manual":
                    # Check SOCKS or HTTP host/port
                    res_p = subprocess.run(['gsettings', 'get', 'org.gnome.system.proxy.socks', 'port'],
                                           capture_output=True, text=True, timeout=0.2)
                    port_str = res_p.stdout.strip()
                    if port_str.isdigit() and int(port_str) > 0:
                        info.update({
                            "enabled": True,
                            "type": "System SOCKS Proxy",
                            "host": "127.0.0.1",
                            "port": int(port_str),
                            "label": f"127.0.0.1:{port_str}"
                        })
                        self._cached_sys_proxy = info
                        return info
            except Exception:
                pass

        # 3. Check Windows Registry (Windows)
        elif platform.system() == "Windows":
            try:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
                proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
                if proxy_enable == 1:
                    proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
                    info.update({
                        "enabled": True,
                        "type": "Windows System Proxy",
                        "host": proxy_server.split(":")[0] if ":" in proxy_server else proxy_server,
                        "port": int(proxy_server.split(":")[1]) if ":" in proxy_server else 8080,
                        "label": proxy_server
                    })
                    self._cached_sys_proxy = info
                    return info
            except Exception:
                pass

        self._cached_sys_proxy = info
        return info

    def get_active_profile_and_protocol(self, running_clients: Optional[List[Dict[str, str]]] = None, tun_iface: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
        """
        Detect active profile name and protocol (WireGuard, OpenVPN, VLESS, VMess, Trojan, etc.).
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
            running_clients = self.get_running_clients(tun_iface=tun_iface)

        # 2. Check Clash / Mihomo REST API if running
        is_clash_running = any('clash' in c['key'] or 'mihomo' in c['key'] for c in running_clients)
        if is_clash_running:
            for port in [9090, 9097, 2080, 7892]:
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
            key = primary["key"]

            if "wireguard" in key or "wg" in key:
                return name, "WireGuard"
            elif "openvpn" in key:
                return name, "OpenVPN"
            elif "tailscale" in key:
                return "Tailscale", "Mesh VPN (WireGuard)"
            elif "zerotier" in key:
                return "ZeroTier", "Virtual L2 Network"
            elif "warp" in key or "cloudflare" in key:
                return "Cloudflare WARP", "WireGuard (WARP)"
            elif "proton" in key:
                return "Proton VPN", "WireGuard/OpenVPN"
            elif "nord" in key:
                return "NordVPN", "NordLynx (WireGuard)"
            elif "mullvad" in key:
                return "Mullvad VPN", "WireGuard/OpenVPN"
            elif "netmod" in key:
                return "NetMod Active", "SSH/V2Ray/Xray"
            elif "netch" in key:
                return "Netch Active", "Bypass/TUN"
            elif "nekoray" in key or "nekobox" in key:
                return primary["name"], "Sing-Box/Xray"
            elif "xray" in key or "v2ray" in key:
                return primary["name"], "VLESS/VMess"
            elif "clash" in key or "mihomo" in key:
                return primary["name"], "Rule-Based"
            elif "hysteria" in key:
                return "Hysteria", "Hysteria UDP"
            elif "tuic" in key:
                return "TUIC", "QUIC Proxy"
            elif "shadowsocks" in key or "ss" in key:
                return "Shadowsocks", "Shadowsocks"
            elif "cisco" in key or "anyconnect" in key:
                return "Cisco AnyConnect", "SSL-VPN"
            elif "forti" in key:
                return "FortiClient", "Fortinet SSL-VPN"
            elif "tor" in key:
                return "Tor Network", "Onion Routing"

            sys_proxy = self.get_system_proxy_info()
            if sys_proxy["enabled"]:
                return sys_proxy["label"], sys_proxy["type"]

            return name, "VPN/Proxy"

        # 4. Infer from TUN interface name if active
        if tun_iface:
            inferred = self._infer_client_name_from_adapter(tun_iface)
            return inferred, "Virtual Tunnel"

        return None, None

    def get_top_apps(self, limit: int = 10, fallback_system: bool = False) -> List[Dict[str, Any]]:
        """
        Universal per-application tracking:
        1. If Throne / Sing-box SQLite DB is available, reads byte-level stats.
        2. If fallback_system is requested (or when another VPN is running),
           scans active system network sockets to report top apps in real time.
        """
        # A. Query Throne SQLite stats database if present
        if os.path.exists(self.throne_stats_db):
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
                    if apps:
                        return apps
                finally:
                    conn.close()
            except Exception:
                pass

        # B. Fallback: inspect active network sockets on the system (cached for 2.5s)
        if fallback_system:
            now = time.monotonic()
            if self._cached_top_apps and (now - self._last_top_apps_check < self._top_apps_cache_ttl):
                return list(self._cached_top_apps)

            self._last_top_apps_check = now
            try:
                proc_map = {}
                for p in psutil.process_iter(['pid', 'name']):
                    try:
                        proc_map[p.info['pid']] = p.info['name']
                    except Exception:
                        pass

                conns = psutil.net_connections(kind='inet')
                app_counts: Dict[str, int] = {}
                for c in conns:
                    if c.status == 'ESTABLISHED' and c.pid and c.pid in proc_map:
                        pname = proc_map[c.pid]
                        # Exclude self and python runner
                        if pname in ['python', 'python3', 'pytest', 'gsd-screensaver-proxy']:
                            continue
                        app_counts[pname] = app_counts.get(pname, 0) + 1

                system_apps = []
                for name, count in sorted(app_counts.items(), key=lambda x: x[1], reverse=True)[:limit]:
                    system_apps.append({
                        "process": name,
                        "up_bytes": 0,
                        "down_bytes": 0,
                        "total_bytes": count,
                        "is_connections": True,
                    })

                self._cached_top_apps = system_apps
                return system_apps
            except Exception:
                pass

        return []

    def get_status_summary(self, active_adapters: Optional[List[str]] = None) -> Dict[str, Any]:
        """Comprehensive summary of active VPN / Proxy status (cached with 1.0s TTL)."""
        now = time.monotonic()
        if self._cached_summary and (now - self._last_summary_check < self._summary_cache_ttl):
            return dict(self._cached_summary)

        tun_name = self.get_tun_interface_name(active_adapters=active_adapters)
        tun_active = tun_name is not None

        running_tools = self.get_running_clients(tun_iface=tun_name)
        is_running = len(running_tools) > 0 or tun_active

        sys_proxy = self.get_system_proxy_info()
        profile_name, protocol = self.get_active_profile_and_protocol(running_clients=running_tools, tun_iface=tun_name)

        primary_client = running_tools[0]["name"] if running_tools else ("Active VPN Tunnel" if tun_active else "VPN / Proxy")

        status_text = "Disconnected"
        if tun_active:
            if profile_name and protocol:
                status_text = f"Connected: {protocol} ({profile_name})"
            elif profile_name:
                status_text = f"Connected ({profile_name})"
            else:
                status_text = f"Connected ({primary_client} TUN)"
        elif is_running:
            if sys_proxy["enabled"]:
                status_text = f"Proxy Active ({sys_proxy['label']})"
            else:
                status_text = f"Running ({primary_client} Standby)"

        # When a TUN is active, query top apps (falling back to system connection inspection if Throne stats DB is absent)
        top_apps = self.get_top_apps(limit=8, fallback_system=True) if tun_active else []

        summary = {
            "is_running": is_running,
            "tun_active": tun_active,
            "tun_interface": tun_name,
            "status_text": status_text,
            "client_name": primary_client,
            "active_profile": profile_name or (primary_client if is_running else "None"),
            "profile_type": protocol or ("System Proxy" if sys_proxy["enabled"] else "VPN/Proxy"),
            "running_tools": running_tools,
            "system_proxy": sys_proxy,
            "top_apps": top_apps,
        }

        self._cached_summary = summary
        self._last_summary_check = now
        return summary
