#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

if [ ! -d "venv" ]; then
    echo "[*] Creating Python virtual environment with system site packages..."
    python3 -m venv --system-site-packages venv
    source venv/bin/activate
    pip install -r requirements.txt --quiet || true
else
    source venv/bin/activate
fi

if [ "$1" == "--install" ] || [ "$1" == "--setup" ]; then
    echo "[*] Installing/updating dependencies..."
    pip install -r requirements.txt --quiet || true
    shift
fi

echo "[*] Launching Network Monitor..."
exec python3 main.py "$@"
