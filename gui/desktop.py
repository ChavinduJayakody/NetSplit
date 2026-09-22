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
from web.server import start_web_server


def run_desktop_app(collector: NetworkCollector, host: str = "127.0.0.1", port: int = 8765):
    """
    Launch native desktop application window.
    Runs an internal lightweight web server on localhost and binds it to a native desktop window.
    """
    server = start_web_server(collector, host=host, port=port)
    url = f"http://{host}:{port}"

    # Setup native window
    window = webview.create_window(
        title="NetSplit | Wi-Fi & Throne VPN Split Monitor",
        url=url,
        width=1120,
        height=780,
        min_size=(720, 540),
        background_color="#0d1117",
        text_select=True,
    )

    # Start desktop event loop
    try:
        webview.start(debug=False)
    finally:
        collector.stop()
