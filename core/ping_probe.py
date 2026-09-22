"""
Ping probe and public IP detection module.
Cross-platform support for Linux and Windows.
Performs non-blocking latency measurements for Wi-Fi gateway and public internet.
"""

import subprocess
import threading
import time
import urllib.request
import re
import platform
from typing import Dict, Any, Optional

from core.security import validate_host, validate_ip


class PingProbe:
    def __init__(self, target_dns: str = "1.1.1.1", gateway_ip: Optional[str] = None):
        self.target_dns = target_dns
        self.gateway_ip: Optional[str] = gateway_ip
        self.gateway_ping_ms: Optional[float] = None
        self.internet_ping_ms: Optional[float] = None
        self.public_ip: Optional[str] = None
        self.last_public_ip_check: float = 0.0

        self.is_windows = platform.system() == "Windows"
        self._running = True
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def update_gateway(self, gw_ip: Optional[str]):
        with self._lock:
            self.gateway_ip = gw_ip

    def _ping_host(self, host: str, timeout_sec: int = 1) -> Optional[float]:
        if not host or not validate_host(host):
            return None
        try:
            if self.is_windows:
                cmd = ['ping', '-n', '1', '-w', str(int(timeout_sec * 1000)), host]
            else:
                cmd = ['ping', '-c', '1', '-W', str(timeout_sec), host]

            res = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=timeout_sec + 0.8
            )
            if res.returncode == 0:
                match = re.search(r'time[=<]\s*([\d\.]+)\s*ms', res.stdout, re.IGNORECASE)
                if match:
                    return float(match.group(1))
        except Exception:
            pass
        return None

    def _fetch_public_ip(self) -> Optional[str]:
        endpoints = [
            'https://api.ipify.org',
            'https://icanhazip.com',
            'https://1.1.1.1/cdn-cgi/trace',
        ]
        for url in endpoints:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'curl/8.0'})
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    data = resp.read().decode('utf-8', errors='ignore').strip()
                    if 'cdn-cgi/trace' in url:
                        for line in data.splitlines():
                            if line.startswith('ip='):
                                cand = line.split('=')[1].strip()
                                if validate_ip(cand):
                                    return cand
                    else:
                        match = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', data)
                        if match:
                            cand = match.group(0)
                            if validate_ip(cand):
                                return cand
            except Exception:
                continue
        return None

    def _worker(self):
        while self._running:
            gw = self.gateway_ip
            gw_ping = None
            if gw:
                gw_ping = self._ping_host(gw)

            inet_ping = self._ping_host(self.target_dns)

            now = time.time()
            pub_ip = self.public_ip
            if now - self.last_public_ip_check > 45 or self.public_ip is None:
                new_ip = self._fetch_public_ip()
                if new_ip:
                    pub_ip = new_ip
                    self.last_public_ip_check = now

            with self._lock:
                self.gateway_ping_ms = gw_ping
                self.internet_ping_ms = inet_ping
                self.public_ip = pub_ip

            time.sleep(3)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "gateway_ping_ms": self.gateway_ping_ms,
                "internet_ping_ms": self.internet_ping_ms,
                "public_ip": self.public_ip or "Checking...",
            }

    def stop(self):
        self._running = False
