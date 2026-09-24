"""
Cross-platform utilities for executing commands cleanly and managing platform details.
Guarantees 100% suppressed console windows on Windows (prevents CMD loop/flicker in GUI mode).
"""

import os
import sys
import platform
import subprocess
from typing import Optional, List, Dict, Any


def is_windows() -> bool:
    return platform.system() == "Windows"


def is_linux() -> bool:
    return platform.system() == "Linux"


def get_windows_hidden_kwargs() -> Dict[str, Any]:
    """Return subprocess kwargs to completely hide console windows on Windows."""
    kwargs: Dict[str, Any] = {}
    if is_windows():
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
            startupinfo.wShowWindow = 0  # SW_HIDE
            kwargs["startupinfo"] = startupinfo
    return kwargs


def run_command_hidden(cmd: List[str], timeout: float = 2.0, **extra_kwargs) -> subprocess.CompletedProcess:
    """
    Execute a subprocess with guaranteed hidden console window on Windows.
    Safely captures output and prevents CMD popup/flash loops.
    """
    kwargs = get_windows_hidden_kwargs()
    kwargs.update({
        "capture_output": True,
        "text": True,
        "timeout": timeout,
    })
    kwargs.update(extra_kwargs)
    return subprocess.run(cmd, **kwargs)


def ensure_std_streams():
    """Ensure sys.stdout and sys.stderr are not None (common in pyinstaller --noconsole)."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
