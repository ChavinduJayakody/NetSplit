#!/usr/bin/env python3
"""
NetSplit - Automated Programmatic Screenshot Generator.
Captures high-resolution, pixel-perfect PNG screenshots of every view
using native GTK 4 / GSK surface rendering without requiring external tools.

Uses fully fabricated demo data — no real network, IPs, or VPN info is exposed.
"""

import os
import sys
import time

# Ensure project root is in path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gsk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Gdk, Gsk, Adw, GLib

from gui.app import MainWindow

# ---------------------------------------------------------------------------
# DEMO / DUMMY SNAPSHOT  — completely fabricated, RFC 5737 / RFC 3849 safe
# ---------------------------------------------------------------------------
MB = 1024 * 1024
GB = 1024 * MB

DEMO_SNAPSHOT = {
    "speeds": {
        "normal_down_bps": 28_672,          # 28.0 KB/s
        "normal_up_bps":    5_120,           # 5.0 KB/s
        "vpn_down_bps":  1_310_720,          # 1.25 MB/s
        "vpn_up_bps":      204_800,          # 200 KB/s
        "total_down_bps": 1_339_392,
        "total_up_bps":    209_920,
        "normal_down_str": "28.0 KB/s",
        "normal_up_str":   "5.0 KB/s",
        "vpn_down_str":    "1.25 MB/s",
        "vpn_up_str":      "200.0 KB/s",
        "total_down_str":  "1.27 MB/s",
        "total_up_str":    "205.0 KB/s",
    },
    "session_usage": {
        "normal_rx":   45 * MB,
        "normal_tx":   12 * MB,
        "normal_total": 57 * MB,
        "normal_total_str": "57.0 MB",
        "vpn_rx":    780 * MB,
        "vpn_tx":    210 * MB,
        "vpn_total": 990 * MB,
        "vpn_total_str":    "990.0 MB",
        "total_rx":  825 * MB,
        "total_tx":  222 * MB,
        "grand_total": 1047 * MB,
        "grand_total_str":  "1.02 GB",
    },
    "today_usage": {
        "normal_rx":   210 * MB,
        "normal_tx":    63 * MB,
        "normal_total": 273 * MB,
        "normal_total_str": "273.0 MB",
        "vpn_rx":   2_800 * MB,
        "vpn_tx":     640 * MB,
        "vpn_total": 3_440 * MB,
        "vpn_total_str":   "3.36 GB",
        "total_rx":  3_010 * MB,
        "total_tx":    703 * MB,
        "grand_total": 3_713 * MB,
        "grand_total_str": "3.62 GB",
    },
    "wifi": {
        "ssid":     "NetSplit-Demo-5G",
        "signal":   82,
        "bars":     "████░",
        "bitrate":  "540 Mbit/s",
        "band":     "5 GHz",
        "channel":  "36",
        "security": "WPA2",
        "local_ip": "192.168.1.100",
    },
    "ping": {
        "gateway_ping_ms": 3.21,
        "internet_ping_ms": 11.74,
        "public_ip": "203.0.113.42",   # RFC 5737 TEST-NET, safe for docs
    },
    "vpn": {
        "tun_active":      True,
        "status_text":     "Connected",
        "client_name":     "NetSplit Demo",
        "active_profile":  "DemoServer-US (VLESS)",
        "profile_type":    "VLESS",
        "tun_interface":   "tun0",
        "running_tools": [
            {"name": "xray"},
        ],
        "top_apps": [
            {"process": "firefox",  "up_bytes": int(1.8*GB), "down_bytes": int(2.4*GB), "total_bytes": int(4.2*GB)},
            {"process": "code",     "up_bytes": int(0.3*GB), "down_bytes": int(1.1*GB), "total_bytes": int(1.4*GB)},
            {"process": "spotify",  "up_bytes": int(0.1*GB), "down_bytes": int(0.9*GB), "total_bytes": int(1.0*GB)},
            {"process": "discord",  "up_bytes": int(0.2*GB), "down_bytes": int(0.6*GB), "total_bytes": int(0.8*GB)},
            {"process": "telegram", "up_bytes": int(0.05*GB),"down_bytes": int(0.3*GB), "total_bytes": int(0.35*GB)},
        ],
    },
    "throne": {   # alias kept for compat
        "tun_active":      True,
        "status_text":     "Connected",
        "client_name":     "NetSplit Demo",
        "active_profile":  "DemoServer-US (VLESS)",
        "profile_type":    "VLESS",
        "tun_interface":   "tun0",
        "running_tools": [
            {"name": "xray"},
        ],
        "top_apps": [
            {"process": "firefox",  "up_bytes": int(1.8*GB), "down_bytes": int(2.4*GB), "total_bytes": int(4.2*GB)},
            {"process": "code",     "up_bytes": int(0.3*GB), "down_bytes": int(1.1*GB), "total_bytes": int(1.4*GB)},
            {"process": "spotify",  "up_bytes": int(0.1*GB), "down_bytes": int(0.9*GB), "total_bytes": int(1.0*GB)},
            {"process": "discord",  "up_bytes": int(0.2*GB), "down_bytes": int(0.6*GB), "total_bytes": int(0.8*GB)},
            {"process": "telegram", "up_bytes": int(0.05*GB),"down_bytes": int(0.3*GB), "total_bytes": int(0.35*GB)},
        ],
    },
    "speed_history": [
        # 30 plausible data-points matching collector format (all bps)
        {"timestamp": 0, "normal_down":   900_000, "normal_up": 150_000, "vpn_down":  900_000, "vpn_up": 150_000, "total_down": 1_050_000, "total_up": 180_000},
        {"timestamp": 1, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down":  950_000, "vpn_up": 160_000, "total_down": 1_100_000, "total_up": 190_000},
        {"timestamp": 2, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_050_000,"vpn_up": 180_000, "total_down": 1_200_000, "total_up": 200_000},
        {"timestamp": 3, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_100_000,"vpn_up": 190_000, "total_down": 1_180_000, "total_up": 195_000},
        {"timestamp": 4, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_200_000,"vpn_up": 200_000, "total_down": 1_250_000, "total_up": 210_000},
        {"timestamp": 5, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_180_000,"vpn_up": 195_000, "total_down": 1_300_000, "total_up": 205_000},
        {"timestamp": 6, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_250_000,"vpn_up": 210_000, "total_down": 1_280_000, "total_up": 200_000},
        {"timestamp": 7, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_300_000,"vpn_up": 205_000, "total_down": 1_310_720, "total_up": 204_800},
        {"timestamp": 8, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_280_000,"vpn_up": 200_000, "total_down": 1_290_000, "total_up": 198_000},
        {"timestamp": 9, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_310_720,"vpn_up": 204_800, "total_down": 1_350_000, "total_up": 220_000},
        {"timestamp":10, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_290_000,"vpn_up": 198_000, "total_down": 1_400_000, "total_up": 230_000},
        {"timestamp":11, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_350_000,"vpn_up": 220_000, "total_down": 1_380_000, "total_up": 225_000},
        {"timestamp":12, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_400_000,"vpn_up": 230_000, "total_down": 1_320_000, "total_up": 210_000},
        {"timestamp":13, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_380_000,"vpn_up": 225_000, "total_down": 1_250_000, "total_up": 200_000},
        {"timestamp":14, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_320_000,"vpn_up": 210_000, "total_down": 1_200_000, "total_up": 195_000},
        {"timestamp":15, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_250_000,"vpn_up": 200_000, "total_down": 1_150_000, "total_up": 185_000},
        {"timestamp":16, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_200_000,"vpn_up": 195_000, "total_down": 1_100_000, "total_up": 175_000},
        {"timestamp":17, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_150_000,"vpn_up": 185_000, "total_down": 1_050_000, "total_up": 170_000},
        {"timestamp":18, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_100_000,"vpn_up": 175_000, "total_down": 1_020_000, "total_up": 165_000},
        {"timestamp":19, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_050_000,"vpn_up": 170_000, "total_down":   980_000, "total_up": 160_000},
        {"timestamp":20, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_020_000,"vpn_up": 165_000, "total_down": 1_000_000, "total_up": 162_000},
        {"timestamp":21, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down":   980_000,"vpn_up": 160_000, "total_down": 1_080_000, "total_up": 170_000},
        {"timestamp":22, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_000_000,"vpn_up": 162_000, "total_down": 1_200_000, "total_up": 190_000},
        {"timestamp":23, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_080_000,"vpn_up": 170_000, "total_down": 1_310_720, "total_up": 204_800},
        {"timestamp":24, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_200_000,"vpn_up": 190_000, "total_down": 1_340_000, "total_up": 208_000},
        {"timestamp":25, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_310_720,"vpn_up": 204_800, "total_down": 1_310_720, "total_up": 204_800},
        {"timestamp":26, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_340_000,"vpn_up": 208_000, "total_down": 1_300_000, "total_up": 205_000},
        {"timestamp":27, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_310_720,"vpn_up": 204_800, "total_down": 1_310_720, "total_up": 204_800},
        {"timestamp":28, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_300_000,"vpn_up": 205_000, "total_down": 1_310_720, "total_up": 204_800},
        {"timestamp":29, "normal_down":  28_672,   "normal_up":   5_120, "vpn_down": 1_310_720,"vpn_up": 204_800, "total_down": 1_310_720, "total_up": 204_800},
    ],
}


# ---------------------------------------------------------------------------
# Minimal stub DB — satisfies every collector.db.* call in MainWindow
# ---------------------------------------------------------------------------
class DemoDB:
    db_path = os.path.join(project_root, "demo.db")  # won't be created

    def get_mask_ips(self): return True
    def set_mask_ips(self, v): pass
    def get_tray_enabled(self): return True
    def set_tray_enabled(self, v): pass
    def get_minimize_to_tray(self): return False
    def set_minimize_to_tray(self, v): pass
    def get_start_minimized(self): return False
    def set_start_minimized(self, v): pass
    def get_exclusive_mode(self): return True
    def set_exclusive_mode(self, v): pass
    def get_setting(self, key, default=None): return default
    def set_setting(self, key, value): pass
    def get_daily_history(self, days=7):
        # Return plausible weekly history rows as dicts (format expected by app.py)
        rows = [
            ("2024-09-16", int(0.5*GB), int(0.3*GB), int(1.4*GB), int(0.7*GB)),
            ("2024-09-17", int(0.3*GB), int(0.2*GB), int(2.1*GB), int(1.3*GB)),
            ("2024-09-18", int(0.8*GB), int(0.4*GB), int(2.6*GB), int(1.4*GB)),
            ("2024-09-19", int(0.2*GB), int(0.1*GB), int(1.1*GB), int(0.7*GB)),
            ("2024-09-20", int(0.6*GB), int(0.3*GB), int(2.0*GB), int(1.2*GB)),
            ("2024-09-21", int(0.4*GB), int(0.2*GB), int(1.7*GB), int(1.0*GB)),
            ("2024-09-22", int(0.21*GB),int(0.06*GB),int(2.8*GB), int(0.56*GB)),
        ]
        return [
            {
                "date": d, "normal_rx": nr, "normal_tx": nt,
                "vpn_rx": vr, "vpn_tx": vt,
                "total_rx": nr + vr, "total_tx": nt + vt,
            }
            for d, nr, nt, vr, vt in rows[-days:]
        ]



# ---------------------------------------------------------------------------
# Minimal stub collector — only get_snapshot() is needed by the UI
# ---------------------------------------------------------------------------
class DemoCollector:
    """Fake collector that returns static demo data. No system access at all."""

    def __init__(self):
        self.db = DemoDB()
        # speed_history is read directly by the graph drawing code
        from collections import deque
        self.speed_history = deque(DEMO_SNAPSHOT["speed_history"], maxlen=60)

    def get_snapshot(self):
        return DEMO_SNAPSHOT

    # Methods called by MainWindow that must not crash
    def stop(self): pass
    def reset_session(self): pass
    def reset_today(self): pass
    def clear_all_history(self): pass


# ---------------------------------------------------------------------------
# Screenshot capture
# ---------------------------------------------------------------------------
def generate_all_screenshots():
    output_dir = os.path.join(project_root, "assets", "screenshots")
    os.makedirs(output_dir, exist_ok=True)

    collector = DemoCollector()

    import random
    app_id = f"io.github.networkmonitor.s{random.randint(10000,99999)}"
    app = Adw.Application(application_id=app_id)

    def capture_tab(win, name: str, filepath: str):
        win.view_stack.set_visible_child_name(name)
        # Flush GTK main loop so layout and Cairo graph draw
        ctx = GLib.MainContext.default()
        for _ in range(30):
            ctx.iteration(False)

        renderer = win.get_renderer()
        wp = Gtk.WidgetPaintable.new(win)
        snap = Gtk.Snapshot.new()
        wp.snapshot(snap, win.get_width(), win.get_height())
        node = snap.to_node()
        if node and renderer:
            texture = renderer.render_texture(node, None)
            texture.save_to_png(filepath)
            print(f"[+] Saved: {os.path.relpath(filepath, project_root)}")
        else:
            print(f"[!] Could not render: {name}")

    def on_activate(app):
        win = MainWindow(app, collector)
        win.set_default_size(880, 720)
        win.present()

        # Push demo data into UI immediately
        win._on_tick()

        def take_all():
            try:
                capture_tab(win, "overview", os.path.join(output_dir, "overview.png"))
                capture_tab(win, "wifi",     os.path.join(output_dir, "wifi.png"))
                capture_tab(win, "vpn",      os.path.join(output_dir, "vpn.png"))
                capture_tab(win, "settings", os.path.join(output_dir, "settings.png"))
                print("[*] All screenshots generated successfully!")
            except Exception as e:
                import traceback
                print(f"[!] Screenshot error: {e}")
                traceback.print_exc()
            finally:
                app.quit()
            return False

        GLib.timeout_add(500, take_all)

    app.connect("activate", on_activate)
    app.run([])


if __name__ == "__main__":
    generate_all_screenshots()
