#!/usr/bin/env python3
"""
NetworkMonitor - Cross-platform Wi-Fi & Throne VPN Traffic Monitor.
Desktop App for Windows & Linux.
"""

import sys
import os
import argparse
import platform
import time

from core.collector import NetworkCollector


def main():
    parser = argparse.ArgumentParser(
        description="NetworkMonitor - Real-time Network Speed & Throne VPN Traffic Monitor"
    )
    parser.add_argument(
        "--desktop", "--app", action="store_true", default=False,
        help="Launch as native cross-platform Desktop App window (Default on Windows)"
    )
    parser.add_argument(
        "--gnome", action="store_true", default=False,
        help="Launch native GNOME GTK4/Libadwaita application (Linux only)"
    )
    parser.add_argument(
        "--web", action="store_true", default=False,
        help="Launch web dashboard server only (view in standard browser)"
    )
    parser.add_argument(
        "--cli", action="store_true", default=False,
        help="Launch live terminal TUI monitor"
    )
    parser.add_argument(
        "--port", type=int, default=8765,
        help="Port for the internal server (default: 8765)"
    )
    parser.add_argument(
        "--host", type=str, default="127.0.0.1",
        help="Host address to bind to (default: 127.0.0.1)"
    )

    args = parser.parse_args()

    # Determine default mode if none specified
    is_windows = platform.system() == "Windows"
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or is_windows)

    collector = NetworkCollector(sample_interval=1.0)

    try:
        if args.cli:
            from cli.monitor import run_cli
            run_cli(collector)
        elif args.web:
            from web.server import start_web_server
            print(f"[*] Starting NetworkMonitor Web Server at http://{args.host}:{args.port}")
            print("[*] Open http://localhost:8765 in your browser. Press Ctrl+C to stop.")
            start_web_server(collector, host=args.host, port=args.port)
            while True:
                time.sleep(1)
        elif args.gnome:
            if is_windows:
                print("[!] GNOME Libadwaita is not supported on Windows. Launching Desktop App window...")
                from gui.desktop import run_desktop_app
                run_desktop_app(collector, host=args.host, port=args.port)
            else:
                from gui.app import run_gui
                run_gui(collector)
        else:
            # Default behavior
            # On Linux: If GNOME Libadwaita is available, default to native GNOME app unless --desktop is given
            # On Windows: Default to pywebview native Desktop App
            if not has_display:
                print("[!] No graphical display detected. Falling back to CLI mode...")
                from cli.monitor import run_cli
                run_cli(collector)
            elif is_windows or args.desktop:
                from gui.desktop import run_desktop_app
                run_desktop_app(collector, host=args.host, port=args.port)
            else:
                # Linux: check if GNOME / Adw is preferred or fallback to desktop window
                try:
                    import gi
                    gi.require_version('Gtk', '4.0')
                    gi.require_version('Adw', '1')
                    from gui.app import run_gui
                    run_gui(collector)
                except Exception:
                    from gui.desktop import run_desktop_app
                    run_desktop_app(collector, host=args.host, port=args.port)

    except KeyboardInterrupt:
        print("\n[+] Exiting NetworkMonitor...")
    finally:
        collector.stop()


if __name__ == "__main__":
    main()
