"""
Terminal CLI live dashboard for NetworkMonitor.
Provides an interactive, real-time curses/ANSI dashboard in the terminal.
"""

import os
import sys
import time
from core.collector import NetworkCollector, format_bytes, format_speed


def run_cli(collector: NetworkCollector):
    # ANSI color codes
    C_RESET = "\033[0m"
    C_BOLD = "\033[1m"
    C_BLUE = "\033[38;2;56;189;248m"
    C_PURPLE = "\033[38;2;192;132;252m"
    C_GREEN = "\033[38;2;74;222;128m"
    C_YELLOW = "\033[38;2;251;191;36m"
    C_MUTED = "\033[38;2;139;148;158m"
    C_BG_CARD = "\033[48;2;22;27;34m"

    print("\033[?25l", end="")  # Hide cursor
    try:
        while True:
            snap = collector.get_snapshot()
            spd = snap["speeds"]
            session = snap["session_usage"]
            today = snap["today_usage"]
            wifi = snap["wifi"]
            ping = snap["ping"]
            throne = snap["throne"]

            # Clear screen and move to top-left
            out = ["\033[H\033[2J"]
            out.append(f"{C_BOLD}=== NETWORK MONITOR (Wi-Fi & Throne VPN) ==={C_RESET}\n")

            # Status bar
            wifi_status = f"{C_GREEN}CONNECTED ({wifi.get('ssid')}){C_RESET}" if wifi.get('connected') else f"{C_MUTED}DISCONNECTED{C_RESET}"
            vpn_status = f"{C_PURPLE}ACTIVE ({throne.get('active_profile')}){C_RESET}" if throne.get('tun_active') else f"{C_MUTED}DIRECT ONLY{C_RESET}"
            out.append(f"Wi-Fi: {wifi_status}   |   VPN: {vpn_status}\n")

            # Realtime Speeds
            out.append(f"{C_BOLD}---------------- LIVE SPEEDS ----------------{C_RESET}")
            out.append(f"  {C_BLUE}Direct Wi-Fi:{C_RESET}  ↓ {spd['normal_down_str']:<11}  ↑ {spd['normal_up_str']:<11}")
            out.append(f"  {C_PURPLE}Throne VPN:{C_RESET}    ↓ {spd['vpn_down_str']:<11}  ↑ {spd['vpn_up_str']:<11}")
            out.append(f"  {C_GREEN}Combined Total:{C_RESET}↓ {spd['total_down_str']:<11}  ↑ {spd['total_up_str']:<11}\n")

            # Usage Split
            out.append(f"{C_BOLD}---------------- USAGE BREAKDOWN ------------{C_RESET}")
            out.append(f"  Today Direct:   {today['normal_total_str']:<12} (Session: {session['normal_total_str']})")
            out.append(f"  Today VPN:      {today['vpn_total_str']:<12} (Session: {session['vpn_total_str']})")
            out.append(f"  Today Grand Tot:{today['grand_total_str']:<12} (Session: {session['grand_total_str']})\n")

            # Wi-Fi Health & Latency
            gw_p = f"{ping['gateway_ping_ms']:.2f} ms" if ping['gateway_ping_ms'] is not None else "--"
            inet_p = f"{ping['internet_ping_ms']:.2f} ms" if ping['internet_ping_ms'] is not None else "--"
            out.append(f"{C_BOLD}---------------- WI-FI & DIAGNOSTICS --------{C_RESET}")
            out.append(f"  Signal:         {wifi.get('signal', 0)}% {wifi.get('bars', '')}   Bitrate: {wifi.get('bitrate', 'N/A')}")
            out.append(f"  Band / Channel: {wifi.get('band', 'N/A')} (Ch {wifi.get('channel', 'N/A')})")
            out.append(f"  Router Ping:    {gw_p:<10} Internet Ping: {inet_p}")
            out.append(f"  Local IP:       {wifi.get('local_ip', 'N/A'):<15} Public IP: {ping.get('public_ip', 'Checking...')}\n")

            # Top Apps from Throne DB
            if throne.get("top_apps"):
                out.append(f"{C_BOLD}---------------- TOP APPS VIA VPN -----------{C_RESET}")
                for app in throne["top_apps"][:5]:
                    out.append(f"  • {app['process']:<18} {format_bytes(app['total_bytes']):>10} (↓ {format_bytes(app['down_bytes'])} ↑ {format_bytes(app['up_bytes'])})")
                out.append("")

            out.append(f"{C_MUTED}Press Ctrl+C to exit...{C_RESET}")

            sys.stdout.write("\n".join(out) + "\n")
            sys.stdout.flush()
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        print("\033[?25h", end="")  # Restore cursor
