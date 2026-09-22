# NetSplit

A cross-platform real-time network speed and usage monitor tailored for tracking **Direct Wi-Fi Internet** alongside **VPN / Proxy traffic via Throne software**.

Works on **Linux** (CachyOS / Arch / Ubuntu / Fedora) and **Windows** (10 / 11).

---

## Key Features

1. **Split Traffic Accounting (Zero Root/Admin Required)**:
   - **Direct (Normal) Internet**: Measures non-tunneled Wi-Fi data in real-time.
   - **Throne VPN**: Accurately isolates traffic routed through Throne's virtual TUN adapter (`throne-tun` / `wintun` / `sing-box`).
   - **Combined Total**: Monitors physical Wi-Fi link speed and bandwidth.
2. **Real-time Speeds & Live Graph**:
   - 1-second sample rate for download and upload speeds.
   - Live stream chart showing traffic history for the last 30–60 seconds.
3. **Throne Database Integration**:
   - Reads Throne's internal database (`throne_stats.db`) in read-only mode to show top applications consuming VPN data (e.g. Brave, Discord, Steam, Spotify).
4. **Wi-Fi & Network Diagnostics**:
   - Network SSID, BSSID, Signal Quality (%), Signal Bars (`▂▄▆█`).
   - Link Speed / Bitrate capability (e.g., 1170 Mbit/s, 866 Mbit/s).
   - Frequency Band & Channel (2.4 GHz vs 5 GHz).
   - Latency / Ping: Local Gateway (Router Wi-Fi hop) & Internet (Cloudflare 1.1.1.1).
   - Local IP and Public Egress IP detection (identifies when your public IP changes due to VPN).
5. **Persistent Usage History**:
   - Stores session, hourly, and daily usage in a lightweight SQLite database.
6. **Cross-Platform Desktop UI**:
   - **Desktop Window (Windows & Linux)**: Native desktop window with hardware acceleration.
   - **Native GNOME App (Linux)**: Modern Libadwaita / GTK 4 interface matching GNOME.
   - **Web Dashboard**: Modern HTML5/CSS3 dashboard accessible via any browser.
   - **Terminal TUI**: Real-time curses-style dashboard for CLI / terminal sessions.

---

## Quick Start

### On Linux

You can launch using the provided script:
```bash
./run.sh
```

Or manually:
```bash
# Optional: create virtual environment
python3 -m venv --system-site-packages venv
source venv/bin/activate
pip install -r requirements.txt

# Run Desktop App (or native GNOME app)
python3 main.py

# Or run Desktop App window directly:
python3 main.py --desktop

# Or run in Web Browser mode:
python3 main.py --web

# Or run in Terminal CLI mode:
python3 main.py --cli
```

---

### On Windows

1. Double-click **`run.bat`** (or run `run.bat` in Command Prompt / PowerShell).
   - Automatically sets up a virtual environment and installs dependencies (`psutil`, `pywebview`).
   - Opens the Desktop App window using Windows' built-in Microsoft Edge WebView2 runtime.

Or manually via Command Prompt / PowerShell:
```cmd
python -m venv venv
call venv\Scripts\activate.bat
pip install -r requirements.txt

:: Launch Desktop App Window
python main.py --desktop

:: Or Web Dashboard
python main.py --web

:: Or Terminal mode
python main.py --cli
```

---

## Command Line Options

```text
usage: main.py [-h] [--desktop] [--gnome] [--web] [--cli] [--port PORT] [--host HOST]

options:
  -h, --help     Show this help message and exit
  --desktop      Launch cross-platform Desktop App window (Default on Windows)
  --gnome        Launch native GNOME GTK4/Libadwaita application (Linux only)
  --web          Launch web dashboard server only (view in browser)
  --cli          Launch live terminal TUI monitor
  --port PORT    Port for web/desktop server (default: 8765)
  --host HOST    Host address to bind (default: 127.0.0.1)
```

---

## How Normal vs Throne VPN Traffic Is Separated

1. **Wi-Fi Interface**:
   - Physical bytes are polled every second from the network adapter (`wlan0` on Linux, `Wi-Fi` on Windows).
2. **Throne TUN Interface**:
   - When Throne VPN connects, a virtual tunnel adapter is created (`throne-tun` on Linux, `Throne-tun` or `wintun` on Windows).
   - Bytes transferred over this interface are isolated as **VPN Traffic**.
3. **Direct Traffic Calculation**:
   - When Throne VPN is active:
     $$\text{Direct Speed} = \max(0, \text{Physical Wi-Fi Speed} - \text{VPN Speed})$$
   - When Throne VPN is disconnected:
     $$\text{Direct Speed} = \text{Physical Wi-Fi Speed}$$
4. **App Attribution**:
   - Throne logs per-process bandwidth in `throne_stats.db`. NetworkMonitor connects with URI `mode=ro` to safely inspect process consumption without file locks or permissions hurdles.

---

## File Structure

```
NetworkMonitor/
├── core/
│   ├── collector.py     # Main engine: samples counters, computes speeds, splits traffic
│   ├── database.py      # SQLite manager for session & daily statistics
│   ├── ping_probe.py    # Latency ping (Gateway & Internet) and Public IP detection
│   ├── throne.py        # Throne process, TUN detection, and SQLite stats integration
│   └── wifi.py          # Cross-platform Wi-Fi information (nmcli on Linux, netsh on Windows)
├── gui/
│   ├── app.py           # Native GNOME GTK4 / Libadwaita desktop app
│   └── desktop.py       # Cross-platform pywebview desktop window runner
├── web/
│   ├── server.py        # Embedded HTTP/REST/SSE server
│   └── static/
│       └── index.html   # Modern responsive dashboard with Chart.js
├── cli/
│   └── monitor.py       # Terminal TUI live monitor
├── tests/
│   └── test_all.py      # Automated test suite
├── main.py              # Main unified entry point
├── requirements.txt     # Python package requirements
├── run.sh               # Linux launcher script
├── run.bat              # Windows launcher script
└── README.md
```
