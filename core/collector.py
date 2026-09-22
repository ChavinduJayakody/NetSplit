"""
Network Traffic Collector Engine.
Cross-platform support for Linux and Windows.
Polls network counters every second, separates Direct Wi-Fi from Throne VPN traffic,
computes speeds, accumulates session & daily totals, and maintains rolling history.
"""

import time
import threading
import platform
from collections import deque
from typing import Dict, Any, Optional
import psutil

from core.wifi import get_wifi_details, get_default_gateway_and_iface
from core.ping_probe import PingProbe
from core.throne import ThroneMonitor
from core.database import StatsDatabase


def format_bytes(b: int) -> str:
    """Format bytes into human-readable string (KB, MB, GB)."""
    if b < 0:
        b = 0
    if b < 1024:
        return f"{b} B"
    elif b < 1024 ** 2:
        return f"{b / 1024:.1f} KB"
    elif b < 1024 ** 3:
        return f"{b / (1024 ** 2):.2f} MB"
    else:
        return f"{b / (1024 ** 3):.2f} GB"


def format_speed(bps: float) -> str:
    """Format bytes per second into human-readable speed string."""
    if bps < 0:
        bps = 0
    if bps < 1024:
        return f"{bps:.0f} B/s"
    elif bps < 1024 ** 2:
        return f"{bps / 1024:.1f} KB/s"
    else:
        return f"{bps / (1024 ** 2):.2f} MB/s"


class NetworkCollector:
    def __init__(self, sample_interval: float = 1.0, history_length: int = 60):
        self.sample_interval = sample_interval
        self.history_length = history_length

        self.is_windows = platform.system() == "Windows"

        # Interface tracking
        self.wifi_iface, gw = get_default_gateway_and_iface()
        if not self.wifi_iface:
            self.wifi_iface = "Wi-Fi" if self.is_windows else "wlan0"

        self.db = StatsDatabase()
        self.throne = ThroneMonitor()
        self.ping_probe = PingProbe(gateway_ip=gw)

        # Wi-Fi initial info
        self.wifi_info: Dict[str, Any] = get_wifi_details(self.wifi_iface)
        self.last_wifi_check: float = time.time()

        # Raw counter baselines
        self.prev_wifi_rx: Optional[int] = None
        self.prev_wifi_tx: Optional[int] = None
        self.prev_vpn_rx: Optional[int] = None
        self.prev_vpn_tx: Optional[int] = None
        self.prev_timestamp: float = 0.0

        # Current speeds (bytes / sec)
        self.total_rx_speed: float = 0.0
        self.total_tx_speed: float = 0.0
        self.vpn_rx_speed: float = 0.0
        self.vpn_tx_speed: float = 0.0
        self.normal_rx_speed: float = 0.0
        self.normal_tx_speed: float = 0.0

        # Session totals (bytes)
        self.session_normal_rx: int = 0
        self.session_normal_tx: int = 0
        self.session_vpn_rx: int = 0
        self.session_vpn_tx: int = 0
        self.session_total_rx: int = 0
        self.session_total_tx: int = 0

        # Rolling history for realtime charts
        self.speed_history = deque(maxlen=history_length)

        # Concurrency
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _read_interfaces(self) -> Dict[str, Dict[str, int]]:
        """Read network counters per interface using psutil (cross-platform)."""
        interfaces = {}
        try:
            counters = psutil.net_io_counters(pernic=True)
            for iface, s in counters.items():
                interfaces[iface] = {'rx': s.bytes_recv, 'tx': s.bytes_sent}
        except Exception:
            pass
        return interfaces

    def _run_loop(self):
        while self._running:
            start_time = time.time()
            self._sample_traffic(start_time)

            if start_time - self.last_wifi_check > 3.0:
                wifi_data = get_wifi_details(self.wifi_iface)
                with self._lock:
                    self.wifi_info = wifi_data
                if wifi_data.get("gateway_ip"):
                    self.ping_probe.update_gateway(wifi_data["gateway_ip"])
                self.last_wifi_check = start_time

            elapsed = time.time() - start_time
            sleep_time = max(0.1, self.sample_interval - elapsed)
            time.sleep(sleep_time)

    def _sample_traffic(self, now: float):
        interfaces = self._read_interfaces()

        # Resolve physical wifi interface
        wifi_stats = interfaces.get(self.wifi_iface)
        if not wifi_stats:
            # On Windows or Linux if interface name differs, pick best candidate
            for name, stats in interfaces.items():
                low = name.lower()
                if "wi-fi" in low or "wireless" in low or "wlan" in low:
                    self.wifi_iface = name
                    wifi_stats = stats
                    break
            if not wifi_stats and interfaces:
                # Fallback to first non-loopback interface
                for name, stats in interfaces.items():
                    if "lo" not in name.lower() and "loopback" not in name.lower():
                        self.wifi_iface = name
                        wifi_stats = stats
                        break

        wifi_rx = wifi_stats['rx'] if wifi_stats else 0
        wifi_tx = wifi_stats['tx'] if wifi_stats else 0

        # Determine vpn interface
        vpn_iface = self.throne.get_tun_interface_name()
        vpn_active = vpn_iface is not None and vpn_iface in interfaces

        vpn_rx = interfaces[vpn_iface]['rx'] if vpn_active else 0
        vpn_tx = interfaces[vpn_iface]['tx'] if vpn_active else 0

        if self.prev_timestamp > 0:
            dt = max(0.001, now - self.prev_timestamp)

            raw_wifi_rx_delta = max(0, wifi_rx - self.prev_wifi_rx) if self.prev_wifi_rx is not None else 0
            raw_wifi_tx_delta = max(0, wifi_tx - self.prev_wifi_tx) if self.prev_wifi_tx is not None else 0

            if vpn_active and self.prev_vpn_rx is not None:
                vpn_rx_delta = max(0, vpn_rx - self.prev_vpn_rx)
                vpn_tx_delta = max(0, vpn_tx - self.prev_vpn_tx)
            else:
                vpn_rx_delta = 0
                vpn_tx_delta = 0

            # Exclusive mode: When VPN is connected, 100% of traffic is counted as VPN, Direct Wi-Fi is 0.
            if vpn_active:
                normal_rx_delta = 0
                normal_tx_delta = 0
                # Use raw physical traffic carrying the VPN tunnel
                vpn_rx_delta = raw_wifi_rx_delta if raw_wifi_rx_delta > 0 else vpn_rx_delta
                vpn_tx_delta = raw_wifi_tx_delta if raw_wifi_tx_delta > 0 else vpn_tx_delta

                cur_tot_rx_spd = raw_wifi_rx_delta / dt
                cur_tot_tx_spd = raw_wifi_tx_delta / dt
                cur_vpn_rx_spd = cur_tot_rx_spd
                cur_vpn_tx_spd = cur_tot_tx_spd
                cur_norm_rx_spd = 0.0
                cur_norm_tx_spd = 0.0
            else:
                vpn_rx_delta = 0
                vpn_tx_delta = 0
                normal_rx_delta = raw_wifi_rx_delta
                normal_tx_delta = raw_wifi_tx_delta

                cur_tot_rx_spd = raw_wifi_rx_delta / dt
                cur_tot_tx_spd = raw_wifi_tx_delta / dt
                cur_vpn_rx_spd = 0.0
                cur_vpn_tx_spd = 0.0
                cur_norm_rx_spd = cur_tot_rx_spd
                cur_norm_tx_spd = cur_tot_tx_spd

            self.session_normal_rx += normal_rx_delta
            self.session_normal_tx += normal_tx_delta
            self.session_vpn_rx += vpn_rx_delta
            self.session_vpn_tx += vpn_tx_delta
            self.session_total_rx += raw_wifi_rx_delta
            self.session_total_tx += raw_wifi_tx_delta

            self.db.record_traffic(normal_rx_delta, normal_tx_delta, vpn_rx_delta, vpn_tx_delta)

            with self._lock:
                self.total_rx_speed = cur_tot_rx_spd
                self.total_tx_speed = cur_tot_tx_spd
                self.vpn_rx_speed = cur_vpn_rx_spd
                self.vpn_tx_speed = cur_vpn_tx_spd
                self.normal_rx_speed = cur_norm_rx_spd
                self.normal_tx_speed = cur_norm_tx_spd

                self.speed_history.append({
                    "timestamp": now,
                    "normal_down": cur_norm_rx_spd,
                    "normal_up": cur_norm_tx_spd,
                    "vpn_down": cur_vpn_rx_spd,
                    "vpn_up": cur_vpn_tx_spd,
                    "total_down": cur_tot_rx_spd,
                    "total_up": cur_tot_tx_spd,
                })

        self.prev_wifi_rx = wifi_rx
        self.prev_wifi_tx = wifi_tx
        self.prev_vpn_rx = vpn_rx if vpn_active else 0
        self.prev_vpn_tx = vpn_tx if vpn_active else 0
        self.prev_timestamp = now

    def get_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            history_list = list(self.speed_history)
            wifi_snap = dict(self.wifi_info)
            speeds = {
                "normal_down_bps": self.normal_rx_speed,
                "normal_up_bps": self.normal_tx_speed,
                "vpn_down_bps": self.vpn_rx_speed,
                "vpn_up_bps": self.vpn_tx_speed,
                "total_down_bps": self.total_rx_speed,
                "total_up_bps": self.total_tx_speed,
                "normal_down_str": format_speed(self.normal_rx_speed),
                "normal_up_str": format_speed(self.normal_tx_speed),
                "vpn_down_str": format_speed(self.vpn_rx_speed),
                "vpn_up_str": format_speed(self.vpn_tx_speed),
                "total_down_str": format_speed(self.total_rx_speed),
                "total_up_str": format_speed(self.total_tx_speed),
            }
            session_usage = {
                "normal_rx": self.session_normal_rx,
                "normal_tx": self.session_normal_tx,
                "normal_total": self.session_normal_rx + self.session_normal_tx,
                "vpn_rx": self.session_vpn_rx,
                "vpn_tx": self.session_vpn_tx,
                "vpn_total": self.session_vpn_rx + self.session_vpn_tx,
                "total_rx": self.session_total_rx,
                "total_tx": self.session_total_tx,
                "grand_total": self.session_total_rx + self.session_total_tx,
                "normal_total_str": format_bytes(self.session_normal_rx + self.session_normal_tx),
                "vpn_total_str": format_bytes(self.session_vpn_rx + self.session_vpn_tx),
                "grand_total_str": format_bytes(self.session_total_rx + self.session_total_tx),
            }

        today_db = self.db.get_today_stats()
        today_usage = {
            "normal_rx": today_db["normal_rx"],
            "normal_tx": today_db["normal_tx"],
            "normal_total": today_db["normal_rx"] + today_db["normal_tx"],
            "vpn_rx": today_db["vpn_rx"],
            "vpn_tx": today_db["vpn_tx"],
            "vpn_total": today_db["vpn_rx"] + today_db["vpn_tx"],
            "total_rx": today_db["total_rx"],
            "total_tx": today_db["total_tx"],
            "grand_total": today_db["total_rx"] + today_db["total_tx"],
            "normal_total_str": format_bytes(today_db["normal_rx"] + today_db["normal_tx"]),
            "vpn_total_str": format_bytes(today_db["vpn_rx"] + today_db["vpn_tx"]),
            "grand_total_str": format_bytes(today_db["total_rx"] + today_db["total_tx"]),
        }

        ping_stats = self.ping_probe.get_stats()
        throne_stats = self.throne.get_status_summary()

        return {
            "speeds": speeds,
            "session_usage": session_usage,
            "today_usage": today_usage,
            "wifi": wifi_snap,
            "ping": ping_stats,
            "throne": throne_stats,
            "speed_history": history_list[-30:],
        }

    def reset_session(self):
        with self._lock:
            self.session_normal_rx = 0
            self.session_normal_tx = 0
            self.session_vpn_rx = 0
            self.session_vpn_tx = 0
            self.session_total_rx = 0
            self.session_total_tx = 0

    def reset_today(self):
        self.reset_session()
        self.db.reset_today_stats()

    def clear_all_history(self):
        self.reset_session()
        self.db.clear_all_stats()

    def stop(self):
        self._running = False
        self.ping_probe.stop()
