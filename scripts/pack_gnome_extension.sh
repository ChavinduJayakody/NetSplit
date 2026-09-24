#!/usr/bin/env bash
# Pack the NetSplit GNOME Shell Extension into a distribution bundle
# Ready for release and upload to https://extensions.gnome.org

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
SRC_DIR="$ROOT_DIR/gnome-extension"
OUT_DIR="$ROOT_DIR/dist"

mkdir -p "$OUT_DIR"

echo "==> Packing GNOME Shell Extension from $SRC_DIR to $OUT_DIR..."
gnome-extensions pack "$SRC_DIR" --force --out-dir "$OUT_DIR"

echo "==> Packaging complete:"
ls -lh "$OUT_DIR"/*.zip 2>/dev/null || ls -lh "$OUT_DIR"
