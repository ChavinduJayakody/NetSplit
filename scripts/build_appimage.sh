#!/usr/bin/env bash
set -e

# ==============================================================================
# NetSplit Linux AppImage Build Script
# Creates a standalone portable AppImage for Linux x86_64
# ==============================================================================

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
PROJECT_ROOT="$( dirname "$SCRIPT_DIR" )"
BUILD_DIR="$PROJECT_ROOT/build_appimage"
APP_DIR="$BUILD_DIR/NetSplit.AppDir"
OUTPUT_DIR="$PROJECT_ROOT/dist"

echo "============================================="
echo "  Building NetSplit AppImage for Linux x86_64"
echo "============================================="

mkdir -p "$BUILD_DIR"
mkdir -p "$OUTPUT_DIR"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"

# 1. Build standalone executable using PyInstaller
echo "[*] Compiling binary with PyInstaller..."
cd "$PROJECT_ROOT"
if [ -d "venv" ]; then
    PYTHON_CMD="$PROJECT_ROOT/venv/bin/python"
else
    PYTHON_CMD="python3"
fi

$PYTHON_CMD -m pip install --quiet pyinstaller
$PYTHON_CMD -m PyInstaller --clean --noconfirm packaging/NetSplit.spec

# 2. Populate AppDir structure
echo "[*] Populating AppDir structure..."
mkdir -p "$APP_DIR/usr/bin"
mkdir -p "$APP_DIR/usr/share/applications"
mkdir -p "$APP_DIR/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$APP_DIR/usr/share/icons/hicolor/256x256/apps"

cp "$PROJECT_ROOT/dist/NetSplit" "$APP_DIR/usr/bin/netsplit"
cp "$PROJECT_ROOT/netsplit.desktop" "$APP_DIR/usr/share/applications/netsplit.desktop"
cp "$PROJECT_ROOT/netsplit.desktop" "$APP_DIR/netsplit.desktop"
cp "$PROJECT_ROOT/assets/netsplit.svg" "$APP_DIR/usr/share/icons/hicolor/scalable/apps/netsplit.svg"
cp "$PROJECT_ROOT/assets/netsplit.svg" "$APP_DIR/netsplit.svg"
cp "$PROJECT_ROOT/assets/netsplit_256.png" "$APP_DIR/usr/share/icons/hicolor/256x256/apps/netsplit.png"
cp "$PROJECT_ROOT/assets/netsplit_256.png" "$APP_DIR/.DirIcon"

# 3. Create AppRun launcher
cat << 'EOF' > "$APP_DIR/AppRun"
#!/bin/sh
HERE="$(dirname "$(readlink -f "${0}")")"
export PATH="${HERE}/usr/bin:${PATH}"
export LD_LIBRARY_PATH="${HERE}/usr/lib:${LD_LIBRARY_PATH}"
export XDG_DATA_DIRS="${HERE}/usr/share:${XDG_DATA_DIRS}"
exec "${HERE}/usr/bin/netsplit" "$@"
EOF
chmod +x "$APP_DIR/AppRun"

# 4. Package into AppImage using appimagetool
echo "[*] Packaging AppImage..."
if ! command -v appimagetool >/dev/null 2>&1; then
    echo "[*] appimagetool not found in PATH, downloading standalone tool..."
    TOOL_URL="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
    curl -sL "$TOOL_URL" -o "$BUILD_DIR/appimagetool"
    chmod +x "$BUILD_DIR/appimagetool"
    APPIMAGETOOL="$BUILD_DIR/appimagetool"
else
    APPIMAGETOOL="appimagetool"
fi

export ARCH=x86_64
"$APPIMAGETOOL" --appimage-extract-and-run "$APP_DIR" "$OUTPUT_DIR/NetSplit-Linux-x86_64.AppImage" || \
"$APPIMAGETOOL" "$APP_DIR" "$OUTPUT_DIR/NetSplit-Linux-x86_64.AppImage"

echo "============================================="
echo "  [SUCCESS] AppImage created at:"
echo "  $OUTPUT_DIR/NetSplit-Linux-x86_64.AppImage"
echo "============================================="
