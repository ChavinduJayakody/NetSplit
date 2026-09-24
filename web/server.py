"""
Lightweight Web Server for NetworkMonitor.
Provides a REST API and Server-Sent Events (SSE) for real-time browser dashboard updates.
Uses zero external packages (built-in http.server and socketserver).
"""

import os
import json
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Optional

from core.collector import NetworkCollector
from core.security import sanitize_static_path, mask_ip


import sys


def get_static_dir() -> str:
    """Resolve the web static directory whether running from source or frozen binary."""
    if hasattr(sys, "_MEIPASS"):
        for cand in [
            os.path.join(sys._MEIPASS, "web", "static"),
            os.path.join(sys._MEIPASS, "static"),
        ]:
            if os.path.exists(cand):
                return cand
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class NetworkMonitorHandler(BaseHTTPRequestHandler):
    collector: Optional[NetworkCollector] = None
    static_dir: str = get_static_dir()

    def log_message(self, format, *args):
        # Silence default terminal request logs to keep output clean
        pass

    def _send_security_headers(self):
        origin = self.headers.get("Origin", "")
        # Only allow local origins (prevents public web pages from scraping local network stats)
        if origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:"):
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_security_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        clean_path = self.path.split("?")[0].split("#")[0]
        if clean_path in ("/", "/index.html"):
            self._serve_index()
        elif clean_path == "/api/stats":
            self._serve_stats()
        elif clean_path == "/api/settings":
            self._serve_get_settings()
        elif clean_path == "/api/history":
            self._serve_history()
        elif clean_path == "/api/stream":
            self._serve_sse_stream()
        elif clean_path.startswith("/static/"):
            self._serve_static(clean_path[8:])
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        clean_path = self.path.split("?")[0].split("#")[0]
        if not self.collector:
            self.send_error(500, "Collector not attached")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            payload = {}

        if clean_path == "/api/settings":
            self._handle_post_settings(payload)
        elif clean_path == "/api/tools/flush-dns":
            from core.network_tools import flush_dns
            res = flush_dns()
            self._send_json_response(res)
        elif clean_path == "/api/tools/reset-proxy":
            from core.network_tools import reset_system_proxy
            res = reset_system_proxy()
            self._send_json_response(res)
        elif clean_path == "/api/tools/renew-dhcp":
            from core.network_tools import renew_dhcp
            res = renew_dhcp()
            self._send_json_response(res)
        elif clean_path == "/api/tools/reset-today":
            self.collector.reset_today()
            self._send_json_response({"success": True, "message": "Today's usage statistics reset to 0."})
        elif clean_path == "/api/tools/clear-history":
            self.collector.clear_all_history()
            self._send_json_response({"success": True, "message": "All historical database records cleared."})
        else:
            self.send_error(404, "Not Found")

    def _serve_get_settings(self):
        if not self.collector:
            self.send_error(500, "Collector not attached")
            return
        from core.autostart import is_autostart_supported, is_autostart_enabled
        import platform
        payload = {
            "mask_ips": self.collector.db.get_mask_ips(),
            "exclusive_mode": self.collector.db.get_exclusive_mode(),
            "minimize_to_tray": self.collector.db.get_minimize_to_tray(),
            "start_minimized": self.collector.db.get_start_minimized(),
            "tray_enabled": self.collector.db.get_tray_enabled(),
            "custom_vpn_iface": self.collector.db.get_setting("custom_vpn_iface", ""),
            "autostart_supported": is_autostart_supported(),
            "autostart": is_autostart_enabled() if is_autostart_supported() else False,
            "theme": self.collector.db.get_setting("theme", "0"),
            "version": "1.4.0",
            "platform": platform.system(),
        }
        self._send_json_response(payload)

    def _handle_post_settings(self, payload: dict):
        if "mask_ips" in payload:
            self.collector.db.set_mask_ips(bool(payload["mask_ips"]))
        if "exclusive_mode" in payload:
            self.collector.db.set_exclusive_mode(bool(payload["exclusive_mode"]))
        if "minimize_to_tray" in payload:
            self.collector.db.set_minimize_to_tray(bool(payload["minimize_to_tray"]))
        if "start_minimized" in payload:
            self.collector.db.set_start_minimized(bool(payload["start_minimized"]))
        if "tray_enabled" in payload:
            self.collector.db.set_tray_enabled(bool(payload["tray_enabled"]))
        if "theme" in payload:
            self.collector.db.set_setting("theme", str(payload["theme"]))
        if "custom_vpn_iface" in payload:
            val = str(payload["custom_vpn_iface"]).strip()
            self.collector.db.set_setting("custom_vpn_iface", val)
            self.collector.vpn.set_custom_interface(val)
        if "autostart" in payload:
            from core.autostart import set_autostart
            set_autostart(bool(payload["autostart"]))

        self._send_json_response({"success": True, "message": "Settings saved successfully."})

    def _send_json_response(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._send_security_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _get_sanitized_snapshot(self) -> dict:
        if not self.collector:
            return {}
        snapshot = self.collector.get_snapshot()
        mask_enabled = self.collector.db.get_mask_ips()
        if mask_enabled:
            pub = snapshot.get("ping", {}).get("public_ip")
            loc = snapshot.get("wifi", {}).get("local_ip")
            if "ping" in snapshot:
                snapshot["ping"]["public_ip"] = mask_ip(pub)
                snapshot["ping"]["raw_public_ip_masked"] = True
            if "wifi" in snapshot:
                snapshot["wifi"]["local_ip"] = mask_ip(loc)
        return snapshot

    def _serve_index(self):
        index_file = os.path.join(self.static_dir, "index.html")
        if os.path.exists(index_file):
            with open(index_file, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self._send_security_headers()
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404, "Dashboard HTML not found")

    def _serve_stats(self):
        if not self.collector:
            self.send_error(500, "Collector not attached")
            return
        snapshot = self._get_sanitized_snapshot()
        data = json.dumps(snapshot).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_security_headers()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_history(self):
        if not self.collector:
            self.send_error(500, "Collector not attached")
            return
        daily = self.collector.db.get_daily_history(7)
        hourly = self.collector.db.get_hourly_history(24)
        payload = {"daily": daily, "hourly": hourly}
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._send_security_headers()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_sse_stream(self):
        if not self.collector:
            self.send_error(500, "Collector not attached")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._send_security_headers()
        self.end_headers()

        try:
            while True:
                snapshot = self._get_sanitized_snapshot()
                data_str = json.dumps(snapshot)
                msg = f"data: {data_str}\n\n".encode("utf-8")
                self.wfile.write(msg)
                self.wfile.flush()
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_static(self, rel_path: str):
        safe_path = sanitize_static_path(self.static_dir, rel_path)
        if not safe_path or not os.path.exists(safe_path) or os.path.isdir(safe_path):
            self.send_error(404, "File Not Found")
            return

        mime = "text/plain"
        if safe_path.endswith(".css"):
            mime = "text/css"
        elif safe_path.endswith(".js"):
            mime = "application/javascript"
        elif safe_path.endswith(".svg"):
            mime = "image/svg+xml"

        with open(safe_path, "rb") as f:
            content = f.read()

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self._send_security_headers()
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def start_web_server(collector: NetworkCollector, host: str = "127.0.0.1", port: int = 8765):
    NetworkMonitorHandler.collector = collector
    server = ThreadedHTTPServer((host, port), NetworkMonitorHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    return server
