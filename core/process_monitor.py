"""
Process Telemetry Engine.
Provides system-wide per-app live bandwidth usage, active network connections,
and session data accounting without requiring third-party tools or root privileges.
Uses native Linux socket statistics (ss / iproute2) with cross-platform psutil fallback.
"""

import os
import platform
import re
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import psutil

from core.formatting import format_bytes, format_speed


class ProcessMonitor:
    def __init__(self, cache_ttl: float = 0.9):
        self.cache_ttl = cache_ttl
        self._lock = threading.Lock()
        self.is_linux = platform.system() == "Linux"
        self.is_windows = platform.system() == "Windows"

        # Previous raw counters: (proc_name, pid) -> {'sent': int, 'recv': int, 't': float}
        self._prev_counters: Dict[Tuple[str, int], Dict[str, Any]] = {}

        # Session cumulative totals: proc_name -> {'sent': int, 'recv': int}
        self._session_totals: Dict[str, Dict[str, int]] = {}

        # Cached results snapshot
        self._cached_apps: List[Dict[str, Any]] = []
        self._last_sample_t: float = 0.0

    def _sample_linux_ss(self) -> Dict[Tuple[str, int], Dict[str, Any]]:
        """Extract per-socket byte counters and PIDs using native Linux ss -tip."""
        current_data: Dict[Tuple[str, int], Dict[str, Any]] = {}
        try:
            res = subprocess.run(
                ['ss', '-tip'],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=1.5
            )
            lines = res.stdout.splitlines()

            current_proc: Optional[str] = None
            current_pid: Optional[int] = None

            for line in lines:
                m = re.search(r'users:\(\(\"([^\"]+)\",pid=(\d+)', line)
                if m:
                    current_proc = m.group(1)
                    try:
                        current_pid = int(m.group(2))
                    except ValueError:
                        current_pid = 0
                elif ('bytes_sent:' in line or 'bytes_received:' in line) and current_proc:
                    sent_m = re.search(r'bytes_sent:(\d+)', line)
                    recv_m = re.search(r'bytes_received:(\d+)', line)
                    sent = int(sent_m.group(1)) if sent_m else 0
                    recv = int(recv_m.group(1)) if recv_m else 0

                    key = (current_proc, current_pid or 0)
                    if key not in current_data:
                        current_data[key] = {
                            'proc': current_proc,
                            'pid': current_pid or 0,
                            'sent': 0,
                            'recv': 0,
                            'conns': 0
                        }
                    current_data[key]['sent'] += sent
                    current_data[key]['recv'] += recv
                    current_data[key]['conns'] += 1
                    current_proc = None
                    current_pid = None
        except Exception:
            pass

        return current_data

    def _sample_psutil_fallback(self) -> Dict[Tuple[str, int], Dict[str, Any]]:
        """Fallback for Windows and environments where ss is unavailable."""
        current_data: Dict[Tuple[str, int], Dict[str, Any]] = {}
        try:
            conns = psutil.net_connections(kind='inet')
            pid_conns: Dict[int, int] = {}
            for c in conns:
                if c.pid:
                    pid_conns[c.pid] = pid_conns.get(c.pid, 0) + 1

            for pid, count in pid_conns.items():
                try:
                    p = psutil.Process(pid)
                    name = p.name()
                    io = p.io_counters()
                    # io_counters has read_bytes (down) and write_bytes (up)
                    key = (name, pid)
                    current_data[key] = {
                        'proc': name,
                        'pid': pid,
                        'sent': io.write_bytes,
                        'recv': io.read_bytes,
                        'conns': count,
                    }
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass

        return current_data

    def get_process_telemetry(self, limit: int = 30) -> List[Dict[str, Any]]:
        """
        Returns real-time per-application network bandwidth and session usage.
        Cached for sub-second efficiency so frequent GUI ticks don't block.
        """
        now = time.monotonic()
        with self._lock:
            if self._cached_apps and (now - self._last_sample_t < self.cache_ttl):
                return list(self._cached_apps[:limit])
        return self.sample(limit=limit)

    def sample(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Sample process network usage and update cache (safe for background threads)."""
        now = time.monotonic()
        # Sample raw socket / process counters
        if self.is_linux:
            raw_snapshot = self._sample_linux_ss()
            # If ss returned nothing (rare), fall back to psutil
            if not raw_snapshot:
                raw_snapshot = self._sample_psutil_fallback()
        else:
            raw_snapshot = self._sample_psutil_fallback()

        with self._lock:
            # Group multiple PIDs by process name
            grouped: Dict[str, Dict[str, Any]] = {}

            for (proc_name, pid), snap in raw_snapshot.items():
                # Filter internal noise
                if proc_name in ('python', 'python3', 'pytest', 'gsd-screensaver-proxy'):
                    continue

                prev = self._prev_counters.get((proc_name, pid))
                if prev:
                    dt = max(0.1, now - prev['t'])
                    d_down = max(0, snap['recv'] - prev['recv'])
                    d_up = max(0, snap['sent'] - prev['sent'])
                    down_rate = d_down / dt
                    up_rate = d_up / dt
                else:
                    d_down = 0
                    d_up = 0
                    down_rate = 0.0
                    up_rate = 0.0

                # Update session totals
                if proc_name not in self._session_totals:
                    self._session_totals[proc_name] = {'sent': snap['sent'], 'recv': snap['recv']}
                else:
                    if d_up > 0:
                        self._session_totals[proc_name]['sent'] += d_up
                    if d_down > 0:
                        self._session_totals[proc_name]['recv'] += d_down

                if proc_name not in grouped:
                    grouped[proc_name] = {
                        'name': proc_name,
                        'pids': [pid],
                        'down_rate': 0.0,
                        'up_rate': 0.0,
                        'conns': 0,
                        'total_sent': self._session_totals[proc_name]['sent'],
                        'total_recv': self._session_totals[proc_name]['recv'],
                    }

                grouped[proc_name]['down_rate'] += down_rate
                grouped[proc_name]['up_rate'] += up_rate
                grouped[proc_name]['conns'] += snap['conns']
                if pid not in grouped[proc_name]['pids']:
                    grouped[proc_name]['pids'].append(pid)

                self._prev_counters[(proc_name, pid)] = {
                    'sent': snap['sent'],
                    'recv': snap['recv'],
                    't': now,
                }

            # Build clean output rows
            results: List[Dict[str, Any]] = []
            for name, item in grouped.items():
                d_rate = item['down_rate']
                u_rate = item['up_rate']
                t_recv = item['total_recv']
                t_sent = item['total_sent']
                t_total = t_recv + t_sent

                results.append({
                    'name': name,
                    'pids': item['pids'],
                    'down_rate': d_rate,
                    'up_rate': u_rate,
                    'down_rate_str': format_speed(d_rate),
                    'up_rate_str': format_speed(u_rate),
                    'total_recv': t_recv,
                    'total_sent': t_sent,
                    'total_recv_str': format_bytes(t_recv),
                    'total_sent_str': format_bytes(t_sent),
                    'total_bytes': t_total,
                    'total_str': format_bytes(t_total),
                    'conns': item['conns'],
                })

            # Sort by active live throughput first, then total bandwidth
            results.sort(
                key=lambda x: (x['down_rate'] + x['up_rate'], x['total_bytes'], x['conns']),
                reverse=True
            )

            self._cached_apps = results[:limit]
            self._last_sample_t = now
            return list(self._cached_apps)
