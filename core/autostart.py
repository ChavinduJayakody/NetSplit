"""
NetSplit - Autostart on System Boot Manager.
Cross-platform support for Linux (XDG Autostart) and Windows (Registry Run Key).
"""

import os
import sys
import platform


def get_project_root() -> str:
    """Return the absolute path to the NetSplit project root directory."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_launcher_path() -> str:
    """Return the path to run.sh (Linux) or run.bat (Windows)."""
    root = get_project_root()
    if platform.system() == "Windows":
        return os.path.join(root, "run.bat")
    return os.path.join(root, "run.sh")


def is_autostart_supported() -> bool:
    """Check if autostart registration is supported on the current platform."""
    return platform.system() in ("Linux", "Windows")


def is_autostart_enabled() -> bool:
    """Check if NetSplit is currently configured to start on boot."""
    sys_type = platform.system()

    if sys_type == "Linux":
        autostart_path = os.path.expanduser("~/.config/autostart/netsplit.desktop")
        if not os.path.exists(autostart_path):
            return False
        try:
            with open(autostart_path, "r", encoding="utf-8") as f:
                content = f.read()
                if "X-GNOME-Autostart-enabled=false" in content:
                    return False
            return True
        except Exception:
            return False

    elif sys_type == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ
            )
            try:
                val, _ = winreg.QueryValueEx(key, "NetSplit")
                return bool(val)
            except FileNotFoundError:
                return False
            finally:
                winreg.CloseKey(key)
        except Exception:
            return False

    return False


def set_autostart(enabled: bool) -> bool:
    """Enable or disable autostart for NetSplit on system boot."""
    sys_type = platform.system()

    if sys_type == "Linux":
        autostart_dir = os.path.expanduser("~/.config/autostart")
        autostart_path = os.path.join(autostart_dir, "netsplit.desktop")

        if enabled:
            os.makedirs(autostart_dir, exist_ok=True)
            launcher = get_launcher_path()
            content = f"""[Desktop Entry]
Type=Application
Name=NetSplit
Comment=Cross-Platform Network & VPN Traffic Monitor
Exec={launcher} --minimized
Icon=netsplit
Terminal=false
Categories=Network;Monitor;System;
X-GNOME-Autostart-enabled=true
"""
            try:
                with open(autostart_path, "w", encoding="utf-8") as f:
                    f.write(content)
                return True
            except Exception as e:
                print(f"[Autostart] Failed to write autostart desktop file: {e}")
                return False
        else:
            if os.path.exists(autostart_path):
                try:
                    os.remove(autostart_path)
                    return True
                except Exception as e:
                    print(f"[Autostart] Failed to remove autostart desktop file: {e}")
                    return False
            return True

    elif sys_type == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE | winreg.KEY_READ
            )
            try:
                if enabled:
                    launcher = get_launcher_path()
                    cmd = f'"{launcher}" --minimized'
                    winreg.SetValueEx(key, "NetSplit", 0, winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(key, "NetSplit")
                    except FileNotFoundError:
                        pass
                return True
            finally:
                winreg.CloseKey(key)
        except Exception as e:
            print(f"[Autostart] Windows registry update failed: {e}")
            return False

    return False
