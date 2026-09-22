"""
Database module for storing network usage history.
Cross-platform support for Linux and Windows.
"""

import os
import sys
import platform
import sqlite3
import datetime
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

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
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
            conn.commit()

    def record_traffic(self, normal_rx: int, normal_tx: int, vpn_rx: int, vpn_tx: int):
        """Record byte deltas for the current minute/hour and day."""
        if normal_rx <= 0 and normal_tx <= 0 and vpn_rx <= 0 and vpn_tx <= 0:
            return

        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        hour_str = now.strftime("%Y-%m-%d %H:00:00")
        total_rx = normal_rx + vpn_rx
        total_tx = normal_tx + vpn_tx

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
                """, (today_str, normal_rx, normal_tx, vpn_rx, vpn_tx, total_rx, total_tx))

                c.execute("""
                    INSERT INTO hourly_stats (hour_bucket, normal_rx, normal_tx, vpn_rx, vpn_tx)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(hour_bucket) DO UPDATE SET
                        normal_rx = normal_rx + excluded.normal_rx,
                        normal_tx = normal_tx + excluded.normal_tx,
                        vpn_rx = vpn_rx + excluded.vpn_rx,
                        vpn_tx = vpn_tx + excluded.vpn_tx
                """, (hour_str, normal_rx, normal_tx, vpn_rx, vpn_tx))
        finally:
            conn.close()

    def get_today_stats(self) -> Dict[str, int]:
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        conn = self._get_connection()
        try:
            c = conn.cursor()
            c.execute("SELECT * FROM daily_stats WHERE date = ?", (today_str,))
            row = c.fetchone()
            if row:
                return dict(row)
            return {
                "date": today_str,
                "normal_rx": 0, "normal_tx": 0,
                "vpn_rx": 0, "vpn_tx": 0,
                "total_rx": 0, "total_tx": 0
            }
        finally:
            conn.close()

    def get_daily_history(self, days: int = 7) -> List[Dict[str, Any]]:
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
