"""
Throne software integration module.
Cross-platform support for Linux and Windows.
Detects Throne process, active profile, TUN status, and reads per-application VPN stats.
"""

import os
import sys
import platform
import sqlite3
from typing import Dict, List, Any, Optional
import psutil


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


class ThroneMonitor:
    def __init__(self, config_dir: str = None):
        self.config_dir = config_dir
        if not self.config_dir:
            for candidate in get_throne_candidate_dirs():
                if os.path.exists(candidate):
                    self.config_dir = candidate
                    break
            if not self.config_dir:
                self.config_dir = get_throne_candidate_dirs()[0]

        self.db_path = os.path.join(self.config_dir, "throne.db")
        self.stats_db_path = os.path.join(self.config_dir, "throne_stats.db")

    def is_throne_running(self) -> bool:
        """Check if Throne or ThroneCore processes are running via psutil."""
        try:
            for proc in psutil.process_iter(['name']):
                pname = (proc.info['name'] or '').lower()
                if 'throne' in pname or 'sing-box' in pname:
                    return True
        except Exception:
            pass
        return False

    def is_tun_active(self) -> bool:
        """Check if a Throne TUN or virtual adapter is active."""
        tun_name = self.get_tun_interface_name()
        return tun_name is not None

    def get_tun_interface_name(self) -> Optional[str]:
        """
        Return the exact active tun/VPN interface name.
        Checks Linux /sys/class/net and psutil interface names on Windows.
        """
        active_adapters = list(psutil.net_io_counters(pernic=True).keys())

        # Exact / prioritized matches
        prioritized = ["throne-tun", "Throne-tun", "sing-box", "sing-box0", "tun0", "wintun"]
        for p in prioritized:
            if p in active_adapters:
                return p

        # Pattern match for adapters containing 'throne', 'wintun', or starting with 'tun'
        for adapter in active_adapters:
            low = adapter.lower()
            if "throne" in low or "wintun" in low:
                return adapter
            if low.startswith("tun") and not low.startswith("tunnel"):
                return adapter

        # Linux-specific /sys/class/net check
        if platform.system() != "Windows":
            net_dir = "/sys/class/net"
            if os.path.exists(net_dir):
                for iface in os.listdir(net_dir):
                    if iface.startswith("tun") or os.path.exists(os.path.join(net_dir, iface, "tun_flags")):
                        return iface
        return None

    def get_active_profile(self) -> Optional[Dict[str, Any]]:
        """Query Throne configuration database for profiles and active routing settings."""
        if not os.path.exists(self.db_path):
            return None

        try:
            uri = f"file:{self.db_path}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=1.0) as conn:
                c = conn.cursor()
                c.execute("SELECT id, name, type FROM profiles LIMIT 10;")
                profiles = c.fetchall()
                if profiles:
                    return {
                        "id": profiles[0][0],
                        "name": profiles[0][1],
                        "type": profiles[0][2],
                        "all_profiles": [{"id": p[0], "name": p[1], "type": p[2]} for p in profiles]
                    }
        except Exception:
            pass
        return None

    def get_top_apps(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve top applications consuming data through Throne VPN from throne_stats.db."""
        if not os.path.exists(self.stats_db_path):
            return []

        apps = []
        try:
            uri = f"file:{self.stats_db_path}?mode=ro"
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

    def get_status_summary(self) -> Dict[str, Any]:
        """Complete summary of Throne status."""
        running = self.is_throne_running()
        tun_active = self.is_tun_active()
        tun_name = self.get_tun_interface_name()
        profile = self.get_active_profile()

        status_text = "Disconnected"
        if tun_active:
            status_text = f"Connected ({profile['name']})" if profile else "Connected (TUN Active)"
        elif running:
            status_text = "Running (Standby / Disconnected)"

        return {
            "is_running": running,
            "tun_active": tun_active,
            "tun_interface": tun_name,
            "status_text": status_text,
            "active_profile": profile.get("name") if profile else "None",
            "profile_type": profile.get("type") if profile else "N/A",
            "top_apps": self.get_top_apps(limit=8),
        }
