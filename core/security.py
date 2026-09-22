"""
NetSplit - Security & Privacy Module.
Provides input validation, IP address masking, and path sanitization.
"""

import os
import re
import ipaddress
import urllib.parse
from typing import Optional


# Regex for safe hostnames and IP addresses (prevents argument/option injection)
SAFE_HOST_REGEX = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9\.\:\-_]{0,253}$')


def validate_host(host: Optional[str]) -> bool:
    """
    Validate that a host string is a safe hostname or IP address.
    Rejects flags (e.g. '-c'), path separators, shell metacharacters, and whitespace.
    """
    if not host or not isinstance(host, str):
        return False
    host = host.strip()
    if host.startswith("-"):
        return False
    return bool(SAFE_HOST_REGEX.match(host))


def validate_ip(ip_str: Optional[str]) -> bool:
    """
    Validate that an IP string is syntactically a valid IPv4 or IPv6 address.
    """
    if not ip_str or not isinstance(ip_str, str):
        return False
    ip_str = ip_str.strip()
    try:
        ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        return False


def mask_ip(ip: Optional[str]) -> str:
    """
    Mask an IP address to preserve user privacy (e.g. for screenshots, streams).
    IPv4: 192.168.1.100 -> 192.168.***.***
    IPv6: 2402:4000:21c0:1234:5678:9abc:def0:1234 -> 2402:4000:****:****::****
    Sentinels like 'Checking...', 'N/A', '--' are returned unchanged.
    """
    if not ip or not isinstance(ip, str):
        return "--"

    ip_clean = ip.strip()
    if ip_clean in ("Checking...", "N/A", "Disconnected", "--"):
        return ip_clean

    # IPv4 masking
    parts = ip_clean.split(".")
    if len(parts) == 4:
        # Mask the last two octets to protect ISP block and subnet
        return f"{parts[0]}.{parts[1]}.***.***"

    # IPv6 masking
    if ":" in ip_clean:
        try:
            parsed = ipaddress.ip_address(ip_clean)
            if parsed.version == 6:
                hextets = ip_clean.split(":")
                if len(hextets) >= 4:
                    return f"{hextets[0]}:{hextets[1]}:****:****::"
                return f"{hextets[0]}:****::"
        except ValueError:
            pass

    return "***.***.***.***"


def sanitize_static_path(base_dir: str, request_path: str) -> Optional[str]:
    """
    Safely resolve a static asset path, preventing directory traversal attacks.
    Returns normalized absolute path if valid and inside base_dir, else None.
    """
    try:
        # Strip query string and URL-decode, normalizing slashes
        path_without_query = request_path.split("?")[0].split("#")[0]
        decoded = urllib.parse.unquote(path_without_query).replace("\\", "/")

        # Normalize relative path
        norm_rel = os.path.normpath(decoded).lstrip("/")
        full_path = os.path.normpath(os.path.join(base_dir, norm_rel))

        # Ensure resolved path is strictly inside base_dir
        real_base = os.path.realpath(base_dir)
        real_target = os.path.realpath(full_path)

        if (real_target.startswith(real_base + os.sep) or real_target == real_base) and os.path.exists(real_target):
            return real_target
    except Exception:
        pass
    return None
