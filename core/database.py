"""
Database module for storing network usage history.
Cross-platform support for Linux and Windows.

Optimized with:
- In-memory running stats cache for zero-latency, zero-disk get_today_stats() calls
- Batched SQLite write transactions (every 5 seconds) to reduce disk I/O and CPU
- SQLite Write-Ahead Logging (WAL) and synchronous=NORMAL for minimal overhead
"""

import os
import sys
import platform
import sqlite3
import datetime
import threading
import time
from typing import Dict, List, Any


def get_default_data_dir() -> str:
    """Return platform-appropriate data directory."""
    if platform.system() == "Windows":
        appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if appdata:
            path = os.path.join(appdata, "NetworkMonitor")
        else:
            path = os.path.expanduser(r"~\AppData\Local\NetworkMonitor")
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            path = os.path.join(xdg_data, "network-monitor")
        else:
            path = os.path.expanduser("~/.local/share/network-monitor")

    os.makedirs(path, exist_ok=True)
    return path


class StatsDatabase:
    def __init__(self, db_path: str = None):
        if db_path is None:
            base_dir = get_default_data_dir()
            self.db_path = os.path.join(base_dir, "history.db")
        else:
            self.db_path = db_path

        self._lock = threading.Lock()
        self._init_db()

        # In-memory today cache for high accuracy without frequent disk reads
        self._today_cache: Dict[str, Any] = {}
        self._today_date: str = ""
        self._init_today_cache()

        # In-memory pending write buffer for batched SQLite commits
        self._pending_deltas = [0, 0, 0, 0]  # [normal_rx, normal_tx, vpn_rx, vpn_tx]
        self._last_flush_time: float = time.monotonic()
        self._flush_interval: float = 5.0  # seconds

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
        except Exception:
            pass
        return conn

    def _init_db(self):
        conn = self._get_connection()
        try:
            with conn:
                c = conn.cursor()
                c.execute("""
                    CREATE TABLE IF NOT EXISTS daily_stats (
                        date TEXT PRIMARY KEY,
                        normal_rx INTEGER DEFAULT 0,
                        normal_tx INTEGER DEFAULT 0,
                        vpn_rx INTEGER DEFAULT 0,
                        vpn_tx INTEGER DEFAULT 0,
                        total_rx INTEGER DEFAULT 0,
                        total_tx INTEGER DEFAULT 0
                    )
                """)
                c.execute("""
                    CREATE TABLE IF NOT EXISTS hourly_stats (
                        hour_bucket TEXT PRIMARY KEY,
                        normal_rx INTEGER DEFAULT 0,
                        normal_tx INTEGER DEFAULT 0,
                        vpn_rx INTEGER DEFAULT 0,
                        vpn_tx INTEGER DEFAULT 0
                    )
                """)
                c.execute("""
                    CREATE TABLE IF NOT EXISTS app_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                """)
        finally:
            conn.close()

    def _init_today_cache(self):
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        self._today_date = today_str
        conn = self._get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM daily_stats WHERE date = ?", (today_str,))
            row = c.fetchone()
            if row:
                self._today_cache = dict(row)
            else:
                self._today_cache = {
                    "date": today_str,
                    "normal_rx": 0, "normal_tx": 0,
                    "vpn_rx": 0, "vpn_tx": 0,
                    "total_rx": 0, "total_tx": 0
                }
        finally:
            conn.close()

    def get_setting(self, key: str, default: str = None) -> str:
        conn = self._get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
            row = c.fetchone()
            if row:
                return row["value"]
            return default
        finally:
            conn.close()

    def set_setting(self, key: str, value: str):
        conn = self._get_connection()
        try:
            with conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO app_settings (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """, (key, str(value)))
        finally:
            conn.close()

    def get_bool_setting(self, key: str, default: bool = False) -> bool:
        val = self.get_setting(key, None)
        if val is None:
            return default
        return val.lower() in ("true", "1", "yes", "on")

    def set_bool_setting(self, key: str, value: bool):
        self.set_setting(key, "true" if value else "false")

    def get_tray_enabled(self) -> bool:
        return self.get_bool_setting("tray_enabled", default=True)

    def set_tray_enabled(self, enabled: bool):
        self.set_bool_setting("tray_enabled", enabled)

    def get_minimize_to_tray(self) -> bool:
        return self.get_bool_setting("minimize_to_tray", default=True)

    def set_minimize_to_tray(self, enabled: bool):
        self.set_bool_setting("minimize_to_tray", enabled)

    def get_start_minimized(self) -> bool:
        return self.get_bool_setting("start_minimized", default=False)

    def set_start_minimized(self, enabled: bool):
        self.set_bool_setting("start_minimized", enabled)

    def get_mask_ips(self) -> bool:
        return self.get_bool_setting("mask_ips", default=True)

    def set_mask_ips(self, enabled: bool):
        self.set_bool_setting("mask_ips", enabled)

    def get_exclusive_mode(self) -> bool:
        return self.get_bool_setting("exclusive_mode", default=True)

    def set_exclusive_mode(self, enabled: bool):
        self.set_bool_setting("exclusive_mode", enabled)

    def get_tray_display_mode(self) -> str:
        return self.get_setting("tray_display_mode", default="speeds_total")

    def set_tray_display_mode(self, mode: str):
        self.set_setting("tray_display_mode", mode)

    def get_hud_enabled(self) -> bool:
        return self.get_bool_setting("hud_enabled", default=False)

    def set_hud_enabled(self, enabled: bool):
        self.set_bool_setting("hud_enabled", enabled)

    def get_hud_display_mode(self) -> str:
        return self.get_setting("hud_display_mode", default="speeds_total")

    def set_hud_display_mode(self, mode: str):
        self.set_setting("hud_display_mode", mode)

    def get_hud_opacity(self) -> int:
        val = self.get_setting("hud_opacity", "90")
        try:
            return max(30, min(100, int(val)))
        except (ValueError, TypeError):
            return 90

    def set_hud_opacity(self, opacity: int):
        clamped = max(30, min(100, int(opacity)))
        self.set_setting("hud_opacity", str(clamped))

    def get_gnome_ext_enabled(self) -> bool:
        return self.get_bool_setting("gnome_ext_enabled", default=False)

    def set_gnome_ext_enabled(self, enabled: bool):
        self.set_bool_setting("gnome_ext_enabled", enabled)

    def get_gnome_ext_display_mode(self) -> str:
        return self.get_setting("gnome_ext_display_mode", default="sigma_today")

    def set_gnome_ext_display_mode(self, mode: str):
        self.set_setting("gnome_ext_display_mode", mode)

    def flush(self):
        """Flush any pending buffered traffic deltas into SQLite."""
        with self._lock:
            self._flush_locked()

    def _flush_locked(self):
        nrx, ntx, vrx, vtx = self._pending_deltas
        if nrx <= 0 and ntx <= 0 and vrx <= 0 and vtx <= 0:
            return

        # Reset pending buffer
        self._pending_deltas = [0, 0, 0, 0]
        self._last_flush_time = time.monotonic()

        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        hour_str = now.strftime("%Y-%m-%d %H:00:00")
        total_rx = nrx + vrx
        total_tx = ntx + vtx

        conn = self._get_connection()
        try:
            with conn:
                c = conn.cursor()
                c.execute("""
                    INSERT INTO daily_stats (date, normal_rx, normal_tx, vpn_rx, vpn_tx, total_rx, total_tx)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(date) DO UPDATE SET
                        normal_rx = normal_rx + excluded.normal_rx,
                        normal_tx = normal_tx + excluded.normal_tx,
                        vpn_rx = vpn_rx + excluded.vpn_rx,
                        vpn_tx = vpn_tx + excluded.vpn_tx,
                        total_rx = total_rx + excluded.total_rx,
                        total_tx = total_tx + excluded.total_tx
                """, (today_str, nrx, ntx, vrx, vtx, total_rx, total_tx))

                c.execute("""
                    INSERT INTO hourly_stats (hour_bucket, normal_rx, normal_tx, vpn_rx, vpn_tx)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(hour_bucket) DO UPDATE SET
                        normal_rx = normal_rx + excluded.normal_rx,
                        normal_tx = normal_tx + excluded.normal_tx,
                        vpn_rx = vpn_rx + excluded.vpn_rx,
                        vpn_tx = vpn_tx + excluded.vpn_tx
                """, (hour_str, nrx, ntx, vrx, vtx))
        finally:
            conn.close()

    def reset_today_stats(self):
        with self._lock:
            self._pending_deltas = [0, 0, 0, 0]
            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
            self._today_date = today_str
            self._today_cache = {
                "date": today_str,
                "normal_rx": 0, "normal_tx": 0,
                "vpn_rx": 0, "vpn_tx": 0,
                "total_rx": 0, "total_tx": 0
            }
            conn = self._get_connection()
            try:
                with conn:
                    c = conn.cursor()
                    c.execute("DELETE FROM daily_stats WHERE date = ?", (today_str,))
            finally:
                conn.close()

    def clear_all_stats(self):
        with self._lock:
            self._pending_deltas = [0, 0, 0, 0]
            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
            self._today_date = today_str
            self._today_cache = {
                "date": today_str,
                "normal_rx": 0, "normal_tx": 0,
                "vpn_rx": 0, "vpn_tx": 0,
                "total_rx": 0, "total_tx": 0
            }
            conn = self._get_connection()
            try:
                with conn:
                    c = conn.cursor()
                    c.execute("DELETE FROM daily_stats")
                    c.execute("DELETE FROM hourly_stats")
            finally:
                conn.close()

    def record_traffic(self, normal_rx: int, normal_tx: int, vpn_rx: int, vpn_tx: int):
        """Record byte deltas in-memory and periodically batch commit to SQLite."""
        if normal_rx <= 0 and normal_tx <= 0 and vpn_rx <= 0 and vpn_tx <= 0:
            return

        today_str = datetime.datetime.now().strftime("%Y-%m-%d")

        with self._lock:
            # Check if midnight rolled over
            if today_str != self._today_date:
                self._flush_locked()
                self._today_date = today_str
                self._today_cache = {
                    "date": today_str,
                    "normal_rx": 0, "normal_tx": 0,
                    "vpn_rx": 0, "vpn_tx": 0,
                    "total_rx": 0, "total_tx": 0
                }

            # Update in-memory today totals immediately for 100% accurate reads
            tot_rx = normal_rx + vpn_rx
            tot_tx = normal_tx + vpn_tx
            self._today_cache["normal_rx"] += normal_rx
            self._today_cache["normal_tx"] += normal_tx
            self._today_cache["vpn_rx"] += vpn_rx
            self._today_cache["vpn_tx"] += vpn_tx
            self._today_cache["total_rx"] += tot_rx
            self._today_cache["total_tx"] += tot_tx

            # Accumulate into pending buffer
            self._pending_deltas[0] += normal_rx
            self._pending_deltas[1] += normal_tx
            self._pending_deltas[2] += vpn_rx
            self._pending_deltas[3] += vpn_tx

            # Flush if interval elapsed
            if (time.monotonic() - self._last_flush_time) >= self._flush_interval:
                self._flush_locked()

    def get_today_stats(self) -> Dict[str, int]:
        """Return today's usage statistics from memory without disk I/O."""
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            if today_str != self._today_date:
                self._flush_locked()
                self._init_today_cache()
            return dict(self._today_cache)

    def get_daily_history(self, days: int = 7) -> List[Dict[str, Any]]:
        self.flush()  # ensure all buffered traffic is committed before querying
        conn = self._get_connection()
        try:
            c = conn.cursor()
            c.execute("""
                SELECT * FROM daily_stats
                ORDER BY date DESC
                LIMIT ?
            """, (days,))
            rows = c.fetchall()
            return [dict(r) for r in reversed(rows)]
        finally:
            conn.close()

    def get_hourly_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        self.flush()  # ensure all buffered traffic is committed before querying
        conn = self._get_connection()
        try:
            c = conn.cursor()
            c.execute("""
                SELECT * FROM hourly_stats
                ORDER BY hour_bucket DESC
                LIMIT ?
            """, (hours,))
            rows = c.fetchall()
            return [dict(r) for r in reversed(rows)]
        finally:
            conn.close()
