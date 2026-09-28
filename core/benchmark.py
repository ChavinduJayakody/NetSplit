import urllib.request
import time
import threading
import subprocess
import re
import platform
import json
import ssl

class SpeedBenchmark:
    def __init__(self):
        self.is_running = False
        self.results = {
            "status": "idle",
            "idle_ping": 0,
            "idle_jitter": 0,
            "download_speed_mbps": 0,
            "download_ping": 0,
            "download_jitter": 0,
            "upload_speed_mbps": 0,
            "upload_ping": 0,
            "upload_jitter": 0,
            "bufferbloat_grade": "A+"
        }
        self._ping_running = False
        self._current_pings = []
        self._ping_thread = None

    def get_results(self):
        return self.results

    def _ping_worker(self, target="1.1.1.1"):
        is_windows = platform.system() == "Windows"
        # We need continuous fast pings. Ping with small timeout.
        while self._ping_running:
            try:
                if is_windows:
                    cmd = ['ping', '-n', '1', '-w', '1000', target]
                else:
                    cmd = ['ping', '-c', '1', '-W', '1', target]
                
                start_t = time.time()
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                if res.returncode == 0:
                    match = re.search(r'time[=<]\s*([\d\.]+)\s*ms', res.stdout, re.IGNORECASE)
                    if match:
                        p = float(match.group(1))
                        self._current_pings.append(p)
                # Sleep a tiny bit to avoid flooding too hard but keep it continuous
                elapsed = time.time() - start_t
                if elapsed < 0.2:
                    time.sleep(0.2 - elapsed)
            except Exception:
                time.sleep(0.5)

    def _start_ping_monitor(self):
        self._current_pings = []
        self._ping_running = True
        self._ping_thread = threading.Thread(target=self._ping_worker, daemon=True)
        self._ping_thread.start()

    def _stop_ping_monitor(self):
        self._ping_running = False
        if self._ping_thread:
            self._ping_thread.join(timeout=2.0)
        pings = list(self._current_pings)
        self._current_pings = []
        if not pings:
            return 0, 0
        avg_ping = sum(pings) / len(pings)
        if len(pings) > 1:
            diffs = [abs(pings[i] - pings[i-1]) for i in range(1, len(pings))]
            jitter = sum(diffs) / len(diffs)
        else:
            jitter = 0
        return avg_ping, jitter

    def calculate_grade(self):
        # Calculate grade based on max bloat
        idle = self.results["idle_ping"]
        dl = self.results["download_ping"]
        ul = self.results["upload_ping"]
        
        bloat_dl = max(0, dl - idle)
        bloat_ul = max(0, ul - idle)
        max_bloat = max(bloat_dl, bloat_ul)
        
        if max_bloat < 5:
            return "A+"
        elif max_bloat < 15:
            return "A"
        elif max_bloat < 30:
            return "B"
        elif max_bloat < 60:
            return "C"
        elif max_bloat < 120:
            return "D"
        else:
            return "F"

    def run_benchmark(self):
        if self.is_running:
            return
        self.is_running = True
        
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        
        try:
            # 1. Idle Ping
            self.results["status"] = "Measuring Idle Ping..."
            self._start_ping_monitor()
            time.sleep(2.0) # collect some pings
            avg_p, j_p = self._stop_ping_monitor()
            self.results["idle_ping"] = round(avg_p, 1)
            self.results["idle_jitter"] = round(j_p, 1)

            # 2. Download Speed
            self.results["status"] = "Testing Download Speed..."
            self._start_ping_monitor()
            start_time = time.time()
            bytes_down = 25000000 # 25MB
            req = urllib.request.Request(f"https://speed.cloudflare.com/__down?bytes={bytes_down}")
            try:
                with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                    data = resp.read()
            except Exception:
                pass
            dl_time = time.time() - start_time
            avg_p, j_p = self._stop_ping_monitor()
            
            if dl_time > 0:
                self.results["download_speed_mbps"] = round((bytes_down * 8) / (dl_time * 1000000), 2)
            self.results["download_ping"] = round(avg_p, 1)
            self.results["download_jitter"] = round(j_p, 1)
            
            # 3. Upload Speed
            self.results["status"] = "Testing Upload Speed..."
            self._start_ping_monitor()
            start_time = time.time()
            bytes_up = 10000000 # 10MB
            # Create a dummy payload
            payload = b"0" * bytes_up
            req = urllib.request.Request("https://speed.cloudflare.com/__up", data=payload, method="POST")
            req.add_header('Content-Type', 'application/octet-stream')
            try:
                with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                    resp.read()
            except Exception:
                pass
            ul_time = time.time() - start_time
            avg_p, j_p = self._stop_ping_monitor()
            
            if ul_time > 0:
                self.results["upload_speed_mbps"] = round((bytes_up * 8) / (ul_time * 1000000), 2)
            self.results["upload_ping"] = round(avg_p, 1)
            self.results["upload_jitter"] = round(j_p, 1)
            
            self.results["bufferbloat_grade"] = self.calculate_grade()
            self.results["status"] = "Completed"
            
        except Exception as e:
            self.results["status"] = f"Error: {e}"
        finally:
            self._stop_ping_monitor()
            self.is_running = False

    def start_async(self):
        t = threading.Thread(target=self.run_benchmark, daemon=True)
        t.start()
        
