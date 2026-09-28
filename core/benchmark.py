"""
Speed Benchmark & Bufferbloat/Jitter Test Module.
Provides high-accuracy throughput and latency diagnostics similar to Speedtest.net and Fast.com.
Powered by Cloudflare Anycast Edge infrastructure with real server and client geo-telemetry.
"""

import json
import platform
import re
import socket
import ssl
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
}

IATA_CITIES = {
    "CMB": "Colombo, Sri Lanka",
    "SIN": "Singapore",
    "MAA": "Chennai, India",
    "BLR": "Bengaluru, India",
    "BOM": "Mumbai, India",
    "DEL": "New Delhi, India",
    "HYD": "Hyderabad, India",
    "CCU": "Kolkata, India",
    "BKK": "Bangkok, Thailand",
    "KUL": "Kuala Lumpur, Malaysia",
    "HKG": "Hong Kong",
    "NRT": "Tokyo, Japan",
    "HND": "Tokyo, Japan",
    "KIX": "Osaka, Japan",
    "ICN": "Seoul, South Korea",
    "TPE": "Taipei, Taiwan",
    "MNL": "Manila, Philippines",
    "CGK": "Jakarta, Indonesia",
    "SYD": "Sydney, Australia",
    "MEL": "Melbourne, Australia",
    "LHR": "London, United Kingdom",
    "FRA": "Frankfurt, Germany",
    "AMS": "Amsterdam, Netherlands",
    "CDG": "Paris, France",
    "ZRH": "Zurich, Switzerland",
    "MAD": "Madrid, Spain",
    "MXP": "Milan, Italy",
    "DXB": "Dubai, UAE",
    "DOH": "Doha, Qatar",
    "JFK": "New York, USA",
    "EWR": "Newark, USA",
    "IAD": "Washington DC, USA",
    "ORD": "Chicago, USA",
    "DFW": "Dallas, USA",
    "LAX": "Los Angeles, USA",
    "SFO": "San Francisco, USA",
    "SJC": "San Jose, USA",
    "SEA": "Seattle, USA",
    "MIA": "Miami, USA",
    "ATL": "Atlanta, USA",
    "YYZ": "Toronto, Canada",
    "YVR": "Vancouver, Canada",
    "GRU": "São Paulo, Brazil",
    "JNB": "Johannesburg, South Africa",
}


class SpeedBenchmark:
    def __init__(self):
        self.is_running = False
        self._lock = threading.Lock()
        self.results: Dict[str, Any] = {
            "status": "Ready",
            "stage": "idle",
            "progress": 0.0,
            "live_speed_mbps": 0.0,
            # Location & Provider Metadata
            "server_name": "Cloudflare Edge",
            "server_location": "Detecting...",
            "server_colo": "--",
            "client_isp": "Detecting...",
            "client_location": "Detecting...",
            "client_ip": "--",
            # Speed Metrics
            "idle_ping": 0.0,
            "idle_jitter": 0.0,
            "download_speed_mbps": 0.0,
            "download_ping": 0.0,
            "download_jitter": 0.0,
            "upload_speed_mbps": 0.0,
            "upload_ping": 0.0,
            "upload_jitter": 0.0,
            "bufferbloat_grade": "--",
            "grade_description": "Run benchmark to calculate bufferbloat score",
        }

        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE

    def get_results(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self.results)

    def _update_result(self, **kwargs):
        with self._lock:
            self.results.update(kwargs)

    def _measure_tcp_pings(self, target_host: str = "speed.cloudflare.com", port: int = 443, count: int = 7) -> Tuple[float, float]:
        """Measure real network round-trip time using TCP handshake probes."""
        pings: List[float] = []
        for _ in range(count):
            try:
                t0 = time.perf_counter()
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(2.5)
                s.connect((target_host, port))
                dt = (time.perf_counter() - t0) * 1000.0
                s.close()
                pings.append(dt)
                time.sleep(0.06)
            except Exception:
                pass

        if not pings:
            return 0.0, 0.0

        pings.sort()
        # Discard extreme outlier if multiple samples exist
        sample = pings[1:-1] if len(pings) >= 5 else pings
        avg_ping = sum(sample) / len(sample)
        diffs = [abs(sample[i] - sample[i - 1]) for i in range(1, len(sample))]
        jitter = sum(diffs) / len(diffs) if diffs else 0.0
        return round(avg_ping, 1), round(jitter, 1)

    def _fetch_metadata(self):
        """Fetch Cloudflare Edge PoP details and client ISP / Geo location."""
        colo = "UNK"
        country_code = ""
        client_ip = ""

        # Cloudflare CDN trace
        try:
            req = urllib.request.Request("https://speed.cloudflare.com/cdn-cgi/trace", headers=HEADERS)
            with urllib.request.urlopen(req, timeout=5, context=self._ctx) as resp:
                for line in resp.read().decode("utf-8", errors="ignore").splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip()
                        if k == "colo":
                            colo = v
                        elif k == "loc":
                            country_code = v
                        elif k == "ip":
                            client_ip = v
        except Exception:
            pass

        server_loc = IATA_CITIES.get(colo, f"{colo}, {country_code}" if country_code else colo)

        # Client IP Geo and ISP lookup
        client_isp = "Direct Network"
        client_city = ""
        client_country = country_code

        try:
            req = urllib.request.Request("http://ip-api.com/json", headers=HEADERS)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if data.get("status") == "success":
                    client_isp = data.get("isp", client_isp)
                    client_city = data.get("city", "")
                    client_country = data.get("country", client_country)
                    client_ip = data.get("query", client_ip)
        except Exception:
            pass

        if client_city and client_country:
            client_location = f"{client_city}, {client_country}"
        else:
            client_location = client_country or "Unknown"

        self._update_result(
            server_name="Cloudflare Edge",
            server_location=server_loc,
            server_colo=colo,
            client_isp=client_isp,
            client_location=client_location,
            client_ip=client_ip,
        )

    def calculate_grade(self) -> Tuple[str, str]:
        """Calculates bufferbloat grade and human-readable assessment."""
        idle = self.results.get("idle_ping", 0.0)
        dl = self.results.get("download_ping", idle)
        ul = self.results.get("upload_ping", idle)

        bloat_dl = max(0.0, dl - idle)
        bloat_ul = max(0.0, ul - idle)
        max_bloat = max(bloat_dl, bloat_ul)

        if max_bloat < 10.0:
            return "A+", f"Grade A+ (Flawless QoS • Max bloat +{round(max_bloat, 1)}ms • Ideal for gaming & VoIP)"
        elif max_bloat < 25.0:
            return "A", f"Grade A (Excellent QoS • Max bloat +{round(max_bloat, 1)}ms • Negligible buffer delay)"
        elif max_bloat < 60.0:
            return "B", f"Grade B (Good • Max bloat +{round(max_bloat, 1)}ms • Slight latency under full load)"
        elif max_bloat < 120.0:
            return "C", f"Grade C (Fair • Max bloat +{round(max_bloat, 1)}ms • Noticeable buffering during downloads)"
        elif max_bloat < 250.0:
            return "D", f"Grade D (Poor • Max bloat +{round(max_bloat, 1)}ms • High buffer queue latency)"
        else:
            return "F", f"Grade F (Severe Bufferbloat • Max bloat +{round(max_bloat, 1)}ms • Router SQM recommended)"

    def run_benchmark(self):
        if self.is_running:
            return
        self.is_running = True

        try:
            # Stage 1: Discover Server & Client Locations
            self._update_result(
                status="Connecting & discovering optimal server...",
                stage="meta",
                progress=0.10,
                live_speed_mbps=0.0,
            )
            self._fetch_metadata()

            # Stage 2: Measure Idle Ping & Jitter
            self._update_result(
                status="Measuring baseline idle latency...",
                stage="ping",
                progress=0.25,
            )
            idle_ping, idle_jitter = self._measure_tcp_pings(count=8)
            self._update_result(
                idle_ping=idle_ping,
                idle_jitter=idle_jitter,
            )

            # Stage 3: Measure Download Speed & Loaded Latency
            self._update_result(
                status="Testing download throughput & bufferbloat...",
                stage="download",
                progress=0.40,
            )

            stop_dl_ping = False
            dl_pings: List[float] = []

            def _dl_pinger():
                while not stop_dl_ping:
                    try:
                        t0 = time.perf_counter()
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(2.0)
                        s.connect(("speed.cloudflare.com", 443))
                        dt = (time.perf_counter() - t0) * 1000.0
                        s.close()
                        dl_pings.append(dt)
                        time.sleep(0.12)
                    except Exception:
                        pass

            ping_thread = threading.Thread(target=_dl_pinger, daemon=True)
            ping_thread.start()

            # Progressive download: 25MB payload
            dl_url = "https://speed.cloudflare.com/__down?bytes=25000000"
            dl_req = urllib.request.Request(dl_url, headers=HEADERS)

            t_start_dl = time.perf_counter()
            bytes_received = 0
            last_sample_t = t_start_dl

            try:
                with urllib.request.urlopen(dl_req, timeout=18, context=self._ctx) as resp:
                    while True:
                        chunk = resp.read(64 * 1024)
                        if not chunk:
                            break
                        bytes_received += len(chunk)
                        now = time.perf_counter()
                        if now - last_sample_t >= 0.25:
                            elapsed = now - t_start_dl
                            if elapsed > 0:
                                live_mbps = round((bytes_received * 8.0) / (elapsed * 1e6), 2)
                                pct = min(0.68, 0.40 + (bytes_received / 25000000.0) * 0.28)
                                self._update_result(
                                    live_speed_mbps=live_mbps,
                                    download_speed_mbps=live_mbps,
                                    progress=pct,
                                )
                            last_sample_t = now
            except Exception as e:
                # If 25MB takes too long, calculate with whatever was received
                pass

            stop_dl_ping = True
            ping_thread.join(timeout=1.0)

            t_total_dl = time.perf_counter() - t_start_dl
            if t_total_dl > 0 and bytes_received > 0:
                final_dl_mbps = round((bytes_received * 8.0) / (t_total_dl * 1e6), 2)
            else:
                final_dl_mbps = 0.0

            avg_dl_ping = round(sum(dl_pings) / len(dl_pings), 1) if dl_pings else idle_ping
            dl_diffs = [abs(dl_pings[i] - dl_pings[i - 1]) for i in range(1, len(dl_pings))] if len(dl_pings) > 1 else [0.0]
            dl_jitter = round(sum(dl_diffs) / len(dl_diffs), 1) if dl_diffs else 0.0

            self._update_result(
                download_speed_mbps=final_dl_mbps,
                live_speed_mbps=final_dl_mbps,
                download_ping=avg_dl_ping,
                download_jitter=dl_jitter,
                progress=0.70,
            )

            # Stage 4: Measure Upload Speed & Loaded Latency
            self._update_result(
                status="Testing upload throughput & bufferbloat...",
                stage="upload",
                progress=0.72,
            )

            stop_ul_ping = False
            ul_pings: List[float] = []

            def _ul_pinger():
                while not stop_ul_ping:
                    try:
                        t0 = time.perf_counter()
                        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s.settimeout(2.0)
                        s.connect(("speed.cloudflare.com", 443))
                        dt = (time.perf_counter() - t0) * 1000.0
                        s.close()
                        ul_pings.append(dt)
                        time.sleep(0.12)
                    except Exception:
                        pass

            ul_ping_thread = threading.Thread(target=_ul_pinger, daemon=True)
            ul_ping_thread.start()

            # Upload: 6MB payload
            payload_size = 6 * 1024 * 1024
            upload_payload = b"Z" * payload_size
            ul_req = urllib.request.Request(
                "https://speed.cloudflare.com/__up",
                data=upload_payload,
                headers={**HEADERS, "Content-Type": "application/octet-stream"},
                method="POST",
            )

            t_start_ul = time.perf_counter()
            try:
                with urllib.request.urlopen(ul_req, timeout=18, context=self._ctx) as resp:
                    resp.read()
            except Exception:
                pass

            stop_ul_ping = True
            ul_ping_thread.join(timeout=1.0)

            t_total_ul = time.perf_counter() - t_start_ul
            if t_total_ul > 0:
                final_ul_mbps = round((payload_size * 8.0) / (t_total_ul * 1e6), 2)
            else:
                final_ul_mbps = 0.0

            avg_ul_ping = round(sum(ul_pings) / len(ul_pings), 1) if ul_pings else idle_ping
            ul_diffs = [abs(ul_pings[i] - ul_pings[i - 1]) for i in range(1, len(ul_pings))] if len(ul_pings) > 1 else [0.0]
            ul_jitter = round(sum(ul_diffs) / len(ul_diffs), 1) if ul_diffs else 0.0

            self._update_result(
                upload_speed_mbps=final_ul_mbps,
                live_speed_mbps=final_ul_mbps,
                upload_ping=avg_ul_ping,
                upload_jitter=ul_jitter,
                progress=0.95,
            )

            # Stage 5: Calculate Bufferbloat Grade
            grade, desc = self.calculate_grade()
            self._update_result(
                status="Benchmark Complete ✓",
                stage="done",
                progress=1.0,
                bufferbloat_grade=grade,
                grade_description=desc,
            )

        except Exception as e:
            self._update_result(
                status=f"Benchmark Error: {e}",
                stage="error",
                progress=1.0,
                grade_description="An error occurred during speed testing",
            )
        finally:
            self.is_running = False

    def start_async(self):
        t = threading.Thread(target=self.run_benchmark, daemon=True)
        t.start()
