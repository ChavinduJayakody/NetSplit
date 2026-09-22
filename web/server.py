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


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class NetworkMonitorHandler(BaseHTTPRequestHandler):
    collector: Optional[NetworkCollector] = None
    static_dir: str = os.path.join(os.path.dirname(__file__), "static")

    def log_message(self, format, *args):
        # Silence default terminal request logs to keep output clean
        pass

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_index()
        elif self.path == "/api/stats":
            self._serve_stats()
        elif self.path == "/api/history":
            self._serve_history()
        elif self.path == "/api/stream":
            self._serve_sse_stream()
        elif self.path.startswith("/static/"):
            self._serve_static()
        else:
            self.send_error(404, "Not Found")

    def _serve_index(self):
        index_file = os.path.join(self.static_dir, "index.html")
        if os.path.exists(index_file):
            with open(index_file, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(404, "Dashboard HTML not found")

    def _serve_stats(self):
        if not self.collector:
            self.send_error(500, "Collector not attached")
            return
        snapshot = self.collector.get_snapshot()
        data = json.dumps(snapshot).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
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
        self.send_header("Access-Control-Allow-Origin", "*")
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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            while True:
                snapshot = self.collector.get_snapshot()
                data_str = json.dumps(snapshot)
                msg = f"data: {data_str}\n\n".encode("utf-8")
                self.wfile.write(msg)
                self.wfile.flush()
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_static(self):
        rel_path = self.path[8:]  # strip /static/
        safe_path = os.path.normpath(os.path.join(self.static_dir, rel_path))
        if not safe_path.startswith(self.static_dir) or not os.path.exists(safe_path):
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
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def start_web_server(collector: NetworkCollector, host: str = "127.0.0.1", port: int = 8765):
    NetworkMonitorHandler.collector = collector
    server = ThreadedHTTPServer((host, port), NetworkMonitorHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    return server
