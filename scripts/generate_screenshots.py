#!/usr/bin/env python3
"""
NetSplit - Automated Programmatic Screenshot Generator.
Captures high-resolution, pixel-perfect PNG screenshots of every view
using native GTK 4 / GSK surface rendering without requiring external tools.
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

from core.collector import NetworkCollector
from gui.app import MainWindow


def generate_all_screenshots():
    output_dir = os.path.join(project_root, "assets", "screenshots")
    os.makedirs(output_dir, exist_ok=True)

    collector = NetworkCollector(sample_interval=1.0)
    # Give collector a quick moment so numbers are populated
    time.sleep(1.2)

    app = Adw.Application(application_id="io.github.networkmonitor.screenshots")

    def capture_tab(win, name: str, filepath: str):
        win.view_stack.set_visible_child_name(name)
        # Flush GTK main loop so layout and Cairo graph draw
        ctx = GLib.MainContext.default()
        for _ in range(25):
            ctx.iteration(False)

        renderer = win.get_renderer()
        wp = Gtk.WidgetPaintable.new(win)
        snap = Gtk.Snapshot.new()
        wp.snapshot(snap, win.get_width(), win.get_height())
        node = snap.to_node()
        if node and renderer:
            texture = renderer.render_texture(node, None)
            texture.save_to_png(filepath)
            print(f"[+] Saved screenshot: {os.path.relpath(filepath, project_root)}")

    def on_activate(app):
        win = MainWindow(app, collector)
        win.set_default_size(880, 720)
        win.present()

        # Update initial values
        win._on_tick()

        def take_all():
            try:
                # 1. Overview tab
                capture_tab(win, "overview", os.path.join(output_dir, "overview.png"))
                # 2. Wi-Fi tab
                capture_tab(win, "wifi", os.path.join(output_dir, "wifi.png"))
                # 3. VPN tab
                capture_tab(win, "vpn", os.path.join(output_dir, "vpn.png"))
                # 4. Settings tab
                capture_tab(win, "settings", os.path.join(output_dir, "settings.png"))
                print("[*] All screenshots generated successfully!")
            except Exception as e:
                print(f"[!] Screenshot error: {e}")
            finally:
                collector.stop()
                app.quit()
            return False

        GLib.timeout_add(400, take_all)

    app.connect("activate", on_activate)
    app.run([])


if __name__ == "__main__":
    generate_all_screenshots()
