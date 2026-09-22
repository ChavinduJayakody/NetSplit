"""
Cross-platform Desktop Application Runner.
Uses pywebview to provide a native Desktop App Window on both Windows (Edge WebView2)
and Linux (WebKitGTK/Qt).
"""

import sys
import os
import platform
import threading
import webview

from core.collector import NetworkCollector
from core.tray import create_tray_controller
from web.server import start_web_server


def run_desktop_app(collector: NetworkCollector, host: str = "127.0.0.1", port: int = 8765, start_minimized: bool = False):
    """
    Launch native desktop application window.
    Runs an internal lightweight web server on localhost and binds it to a native desktop window.
    Supports system tray and minimize-to-tray on Windows.
    """
    server = start_web_server(collector, host=host, port=port)
    url = f"http://{host}:{port}"

    should_start_hidden = start_minimized or collector.db.get_start_minimized()

    # Setup native window
    window = webview.create_window(
        title="NetSplit | Wi-Fi & VPN Split Monitor",
        url=url,
        width=1120,
        height=780,
        min_size=(720, 540),
        background_color="#0d1117",
        text_select=True,
        hidden=should_start_hidden,
    )

    tray = None

    def on_activate():
        try:
            window.show()
            window.restore()
        except Exception:
            pass

    def on_quit():
        try:
            if tray:
                tray.stop()
            collector.stop()
            window.destroy()
        except Exception:
            pass

    if collector.db.get_tray_enabled():
        tray = create_tray_controller(on_activate=on_activate, on_quit=on_quit)
        tray.start()

    def on_closing():
        if collector.db.get_minimize_to_tray() and collector.db.get_tray_enabled():
            window.hide()
            return False  # Prevent window destruction, keep running in background!
        if tray:
            tray.stop()
        collector.stop()
        return True

    window.events.closing += on_closing

    # Start desktop event loop
    try:
        webview.start(debug=False)
    finally:
        if tray:
            tray.stop()
        collector.stop()

