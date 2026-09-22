#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

if [ ! -d "venv" ]; then
    echo "[*] Creating Python virtual environment with system site packages..."
    python3 -m venv --system-site-packages venv
fi

source venv/bin/activate
pip install -r requirements.txt --quiet

echo "[*] Launching Network Monitor..."
python3 main.py "$@"
