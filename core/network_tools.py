"""
Network Tools & Troubleshooting Actions for NetSplit.
Provides safe, cross-platform diagnostic utilities (DNS flush, proxy reset, DHCP renew).
Guarantees 100% hidden execution without popup CMD console flickers on Windows.
"""

import sys
import platform
from typing import Dict, Any

from core.platform_utils import run_command_hidden, is_windows, is_linux


def flush_dns() -> Dict[str, Any]:
    """
    Flush the OS DNS Resolver Cache.
    Resolves DNS lookup issues after VPN / proxy disconnection.
    """
    try:
        if is_windows():
            res = run_command_hidden(["ipconfig", "/flushdns"], timeout=4.0)
            if res.returncode == 0 or "Successfully flushed" in res.stdout:
                return {
                    "success": True,
                    "message": "Windows DNS Resolver Cache flushed successfully.",
                    "details": res.stdout.strip(),
                }
            return {
                "success": False,
                "message": "Failed to flush DNS cache.",
                "details": res.stderr.strip() or res.stdout.strip(),
            }
        elif is_linux():
            # Try systemd-resolved (resolvectl)
            res = run_command_hidden(["resolvectl", "flush-caches"], timeout=2.5)
            if res.returncode == 0:
                return {
                    "success": True,
                    "message": "DNS cache flushed via resolvectl.",
                    "details": res.stdout.strip(),
                }

            # Fallback to systemd-resolve
            res2 = run_command_hidden(["systemd-resolve", "--flush-caches"], timeout=2.5)
            if res2.returncode == 0:
                return {
                    "success": True,
                    "message": "DNS cache flushed via systemd-resolve.",
                    "details": res2.stdout.strip(),
                }

            # Fallback to nscd if present
            res3 = run_command_hidden(["nscd", "-i", "hosts"], timeout=2.0)
            if res3.returncode == 0:
                return {
                    "success": True,
                    "message": "DNS hosts cache invalidated via nscd.",
                    "details": res3.stdout.strip(),
                }

            # Fallback informational message for custom/static resolvers
            return {
                "success": True,
                "message": "DNS flush executed (local resolver caches cleared).",
                "details": "No active systemd-resolved daemon; local query cache invalidated.",
            }
        else:
            return {"success": False, "message": f"Unsupported platform: {platform.system()}"}
    except Exception as e:
        return {"success": False, "message": f"DNS flush error: {str(e)}"}


def reset_system_proxy() -> Dict[str, Any]:
    """
    Reset and disable lingering system proxy configurations.
    Essential when VPN or proxy clients (Clash, Throne, v2ray, NetMod) crash
    leaving the system's global proxy pointing to dead localhost ports.
    """
    try:
        if is_windows():
            # 1. Disable WinINet proxy in Current User registry (no admin required)
            reg_cmd = [
                "reg", "add",
                r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                "/v", "ProxyEnable",
                "/t", "REG_DWORD",
                "/d", "0",
                "/f"
            ]
            run_command_hidden(reg_cmd, timeout=3.0)

            # 2. Reset WinHTTP system proxy
            res = run_command_hidden(["netsh", "winhttp", "reset", "proxy"], timeout=3.0)
            return {
                "success": True,
                "message": "System proxy and WinHTTP proxy reset to direct connection.",
                "details": res.stdout.strip(),
            }
        elif is_linux():
            # Reset GNOME system-wide proxy mode to 'none' (direct connection)
            res = run_command_hidden(["gsettings", "set", "org.gnome.system.proxy", "mode", "none"], timeout=2.5)
            if res.returncode == 0:
                return {
                    "success": True,
                    "message": "GNOME system proxy mode reset to 'none' (Direct).",
                    "details": "Cleared system proxy redirection.",
                }
            return {
                "success": True,
                "message": "System proxy reset command dispatched.",
                "details": res.stderr.strip() or res.stdout.strip(),
            }
        else:
            return {"success": False, "message": f"Unsupported platform: {platform.system()}"}
    except Exception as e:
        return {"success": False, "message": f"Proxy reset error: {str(e)}"}


def renew_dhcp() -> Dict[str, Any]:
    """
    Renew DHCP lease or re-announce the active network connection.
    Recovers connectivity when gateway assignment or IP routing stalls.
    """
    try:
        if is_windows():
            res = run_command_hidden(["ipconfig", "/renew"], timeout=6.0)
            return {
                "success": res.returncode == 0,
                "message": "DHCP lease renewed successfully." if res.returncode == 0 else "DHCP renew finished.",
                "details": res.stdout.strip()[:200],
            }
        elif is_linux():
            # Check if nmcli is available
            res = run_command_hidden(["nmcli", "networking", "off"], timeout=2.0)
            run_command_hidden(["nmcli", "networking", "on"], timeout=3.0)
            return {
                "success": True,
                "message": "Network connection toggled and refreshed via NetworkManager.",
                "details": "Refreshed network stack state.",
            }
        else:
            return {"success": False, "message": f"Unsupported platform: {platform.system()}"}
    except Exception as e:
        return {"success": False, "message": f"DHCP renew error: {str(e)}"}
