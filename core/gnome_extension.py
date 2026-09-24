"""
NetSplit - GNOME Shell Top Bar Extension Manager.
Specialized for Arch Linux and Arch-based distributions running GNOME Shell 45-50+.
Handles deployment, activation, deactivation, and status querying of the
`netsplit-hud@netsplit.app` top-bar indicator.
"""

import os
import sys
import shutil
import platform
import subprocess
from typing import Optional, Tuple, List


EXTENSION_UUID = "netsplit-hud@chavindujayakody.github.io"
OLD_EXTENSION_UUID = "netsplit-hud@netsplit.app"


def is_linux() -> bool:
    """Return True if running on a Linux platform."""
    return platform.system() == "Linux"


def is_arch_linux() -> bool:
    """
    Detect if the operating system is Arch Linux or an Arch-based derivative
    (e.g., CachyOS, Manjaro, EndeavourOS, ArcoLinux, Garuda).
    """
    if not is_linux():
        return False

    if os.path.exists("/etc/arch-release"):
        return True

    # Inspect /etc/os-release
    if os.path.exists("/etc/os-release"):
        try:
            with open("/etc/os-release", "r", encoding="utf-8") as f:
                content = f.read()
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("ID="):
                        val = line.split("=", 1)[1].strip('"\'').lower()
                        if val == "arch":
                            return True
                    elif line.startswith("ID_LIKE="):
                        val = line.split("=", 1)[1].strip('"\'').lower()
                        if "arch" in val.split():
                            return True
        except Exception:
            pass

    # Check pacman presence
    if shutil.which("pacman") is not None:
        return True

    return False


def is_gnome_available() -> bool:
    """
    Check if GNOME Shell and the gnome-extensions CLI tool are available.
    """
    if not is_linux():
        return False

    # Check desktop environment variables
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or "").upper()
    if "GNOME" not in desktop:
        # Check if gnome-shell executable is in PATH
        if shutil.which("gnome-shell") is None:
            return False

    return shutil.which("gnome-extensions") is not None


def get_user_extension_dir() -> str:
    """Return the user-local GNOME Shell extensions installation path."""
    return os.path.expanduser(f"~/.local/share/gnome-shell/extensions/{EXTENSION_UUID}")


def get_bundled_extension_dir() -> Optional[str]:
    """
    Locate the bundled gnome-extension directory within the application tree.
    """
    # 1. Check relative to this module in repo / installed package
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(base_dir, "gnome-extension")
    if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, "metadata.json")):
        return candidate

    # 2. Check sys._MEIPASS for PyInstaller bundles
    if hasattr(sys, "_MEIPASS"):
        candidate = os.path.join(sys._MEIPASS, "gnome-extension")
        if os.path.isdir(candidate):
            return candidate

    # 3. Check current working directory
    candidate = os.path.join(os.getcwd(), "gnome-extension")
    if os.path.isdir(candidate) and os.path.exists(os.path.join(candidate, "metadata.json")):
        return candidate

    return None


def is_extension_installed() -> bool:
    """Check if the NetSplit extension files exist in the user's GNOME extensions directory."""
    ext_dir = get_user_extension_dir()
    metadata = os.path.join(ext_dir, "metadata.json")
    code = os.path.join(ext_dir, "extension.js")
    return os.path.isfile(metadata) and os.path.isfile(code)


def _get_gsettings_enabled_extensions() -> List[str]:
    """Retrieve the list of enabled GNOME Shell extensions from GSettings."""
    try:
        res = subprocess.run(
            ["gsettings", "get", "org.gnome.shell", "enabled-extensions"],
            capture_output=True,
            text=True,
            timeout=3
        )
        if res.returncode == 0:
            import ast
            return ast.literal_eval(res.stdout.strip())
    except Exception:
        pass
    return []


def _set_gsettings_enabled_extensions(ext_list: List[str]) -> bool:
    """Persist the list of enabled GNOME Shell extensions to GSettings."""
    try:
        seen = set()
        deduped = []
        for x in ext_list:
            if x not in seen:
                seen.add(x)
                deduped.append(x)
        res = subprocess.run(
            ["gsettings", "set", "org.gnome.shell", "enabled-extensions", str(deduped)],
            capture_output=True,
            text=True,
            timeout=3
        )
        return res.returncode == 0
    except Exception:
        return False


def is_extension_enabled() -> bool:
    """Check if the NetSplit extension is currently enabled in GNOME Shell."""
    if not is_gnome_available():
        return False
    try:
        res = subprocess.run(
            ["gnome-extensions", "list", "--enabled"],
            capture_output=True,
            text=True,
            timeout=3
        )
        if res.returncode == 0:
            lines = [line.strip() for line in res.stdout.splitlines()]
            if EXTENSION_UUID in lines:
                return True
    except Exception:
        pass

    # Fallback to checking GSettings
    gsettings_exts = _get_gsettings_enabled_extensions()
    return EXTENSION_UUID in gsettings_exts


def install_extension() -> Tuple[bool, str]:
    """
    Copy extension files into ~/.local/share/gnome-shell/extensions/netsplit-hud@netsplit.app.
    """
    src_dir = get_bundled_extension_dir()
    if not src_dir:
        return False, "Could not find bundled gnome-extension source directory."

    dst_dir = get_user_extension_dir()
    try:
        os.makedirs(dst_dir, exist_ok=True)
        for fname in ["metadata.json", "extension.js", "stylesheet.css"]:
            src_file = os.path.join(src_dir, fname)
            dst_file = os.path.join(dst_dir, fname)
            if os.path.exists(src_file):
                shutil.copy2(src_file, dst_file)

        # Also pack into bundle if gnome-extensions pack is available
        try:
            subprocess.run(
                ["gnome-extensions", "pack", src_dir, "--force", "--out-dir", dst_dir],
                capture_output=True,
                timeout=5
            )
        except Exception:
            pass

        # Clean up old extension folder if it existed with placeholder domain
        old_dir = os.path.expanduser(f"~/.local/share/gnome-shell/extensions/{OLD_EXTENSION_UUID}")
        if os.path.exists(old_dir):
            try:
                shutil.rmtree(old_dir)
            except Exception:
                pass
        old_list = _get_gsettings_enabled_extensions()
        if OLD_EXTENSION_UUID in old_list:
            old_list = [x for x in old_list if x != OLD_EXTENSION_UUID]
            _set_gsettings_enabled_extensions(old_list)

        return True, "Extension installed successfully."
    except Exception as e:
        return False, f"Failed to install extension: {e}"


def enable_extension() -> Tuple[bool, str]:
    """Enable the extension using gnome-extensions CLI and GSettings."""
    if not is_gnome_available():
        return False, "GNOME Shell or gnome-extensions CLI is not available."

    if not is_extension_installed():
        ok, msg = install_extension()
        if not ok:
            return False, msg

    # 1. Register in GSettings enabled-extensions
    current = _get_gsettings_enabled_extensions()
    if EXTENSION_UUID not in current:
        current.append(EXTENSION_UUID)
        _set_gsettings_enabled_extensions(current)

    # 2. Try CLI enable
    try:
        res = subprocess.run(
            ["gnome-extensions", "enable", EXTENSION_UUID],
            capture_output=True,
            text=True,
            timeout=5
        )
        if res.returncode == 0:
            return True, "GNOME Shell extension enabled."
        if "does not exist" in (res.stderr or ""):
            return True, "Extension registered. On Wayland, log out & back in once to show on top bar."
        return False, res.stderr.strip() or "Failed to enable GNOME Shell extension."
    except Exception as e:
        return True, f"Extension registered in settings."


def disable_extension() -> Tuple[bool, str]:
    """Disable the extension using gnome-extensions CLI and GSettings."""
    if not is_gnome_available():
        return False, "GNOME Shell or gnome-extensions CLI is not available."

    # 1. Remove from GSettings enabled-extensions
    current = _get_gsettings_enabled_extensions()
    if EXTENSION_UUID in current:
        current = [x for x in current if x != EXTENSION_UUID]
        _set_gsettings_enabled_extensions(current)

    # 2. Call CLI disable
    try:
        subprocess.run(
            ["gnome-extensions", "disable", EXTENSION_UUID],
            capture_output=True,
            text=True,
            timeout=5
        )
    except Exception:
        pass

    return True, "GNOME Shell extension disabled."


def install_and_enable_extension() -> Tuple[bool, str]:
    """Install and immediately enable the GNOME Shell extension."""
    ok, msg = install_extension()
    if not ok:
        return False, msg
    return enable_extension()
