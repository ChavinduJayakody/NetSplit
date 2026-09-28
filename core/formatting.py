"""
Formatting utilities for network statistics and bandwidth rates.
"""

def format_bytes(b: int) -> str:
    """Format bytes into human-readable string (B, KB, MB, GB)."""
    if b < 0:
        b = 0
    if b < 1024:
        return f"{b} B"
    elif b < 1024 ** 2:
        return f"{b / 1024:.1f} KB"
    elif b < 1024 ** 3:
        return f"{b / (1024 ** 2):.2f} MB"
    else:
        return f"{b / (1024 ** 3):.2f} GB"


def format_speed(bps: float) -> str:
    """Format bytes per second into human-readable speed string (B/s, KB/s, MB/s)."""
    if bps < 0:
        bps = 0
    if bps < 1024:
        return f"{bps:.0f} B/s"
    elif bps < 1024 ** 2:
        return f"{bps / 1024:.1f} KB/s"
    else:
        return f"{bps / (1024 ** 2):.2f} MB/s"
