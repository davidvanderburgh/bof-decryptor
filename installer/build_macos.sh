#!/usr/bin/env bash
# Build macOS DMG for BOF Asset Decryptor
# Requirements: Python 3.10+, PyInstaller, create-dmg (brew install create-dmg)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
VERSION=$(python3 -c "import sys; sys.path.insert(0,'$ROOT_DIR'); from bof_decryptor import __version__; print(__version__)")

echo "=== Building BOF Asset Decryptor v${VERSION} for macOS ==="

# Ensure icon exists
if [ ! -f "$ROOT_DIR/bof_decryptor/icon.png" ]; then
    echo "Generating icon..."
    pip3 install --quiet pillow 2>/dev/null || true
    python3 "$ROOT_DIR/generate_icon.py"
fi

# Generate icns from PNG (macOS sips + iconutil)
ICONSET="$SCRIPT_DIR/build/icon.iconset"
mkdir -p "$ICONSET"
sips -z 16 16     "$ROOT_DIR/bof_decryptor/icon.png" --out "$ICONSET/icon_16x16.png"    2>/dev/null
sips -z 32 32     "$ROOT_DIR/bof_decryptor/icon.png" --out "$ICONSET/icon_16x16@2x.png" 2>/dev/null
sips -z 32 32     "$ROOT_DIR/bof_decryptor/icon.png" --out "$ICONSET/icon_32x32.png"    2>/dev/null
sips -z 64 64     "$ROOT_DIR/bof_decryptor/icon.png" --out "$ICONSET/icon_32x32@2x.png" 2>/dev/null
sips -z 128 128   "$ROOT_DIR/bof_decryptor/icon.png" --out "$ICONSET/icon_128x128.png"  2>/dev/null
sips -z 256 256   "$ROOT_DIR/bof_decryptor/icon.png" --out "$ICONSET/icon_128x128@2x.png" 2>/dev/null
sips -z 256 256   "$ROOT_DIR/bof_decryptor/icon.png" --out "$ICONSET/icon_256x256.png"  2>/dev/null
iconutil -c icns "$ICONSET" -o "$SCRIPT_DIR/build/icon.icns"

# PyInstaller build
echo "Running PyInstaller..."
cd "$ROOT_DIR"
pip3 install --quiet pyinstaller 2>/dev/null || true
pyinstaller \
    --name "BOF Asset Decryptor" \
    --windowed \
    --icon "$SCRIPT_DIR/build/icon.icns" \
    --paths "$ROOT_DIR" \
    --add-data "$ROOT_DIR/bof_decryptor/icon.png:bof_decryptor" \
    --noconfirm \
    --clean \
    --distpath "$SCRIPT_DIR/build/dist" \
    --workpath "$SCRIPT_DIR/build/work" \
    --specpath "$SCRIPT_DIR/build" \
    "$SCRIPT_DIR/pyinstaller_entry.py"

APP_PATH="$SCRIPT_DIR/build/dist/BOF Asset Decryptor.app"

# Ad-hoc code sign so macOS doesn't flag the app as "damaged"
echo "Ad-hoc code signing..."
codesign --force --deep --sign - "$APP_PATH"

# Generate DMG background with arrow
echo "Generating DMG background..."
python3 "$ROOT_DIR/installer/generate_dmg_background.py" "$SCRIPT_DIR/build/dmg_background.tiff"

# Create DMG
echo "Creating DMG..."
mkdir -p "$SCRIPT_DIR/Output"
DMG_NAME="BOF_Asset_Decryptor_v${VERSION}.dmg"
if command -v create-dmg &>/dev/null; then
    create-dmg \
        --volname "BOF Asset Decryptor" \
        --volicon "$SCRIPT_DIR/build/icon.icns" \
        --background "$SCRIPT_DIR/build/dmg_background.tiff" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --icon "BOF Asset Decryptor.app" 150 190 \
        --app-drop-link 450 190 \
        "$SCRIPT_DIR/Output/$DMG_NAME" \
        "$APP_PATH"
else
    echo "create-dmg not found, creating basic DMG with hdiutil..."
    hdiutil create -srcfolder "$APP_PATH" \
        -volname "BOF Asset Decryptor" \
        -format UDZO \
        "$SCRIPT_DIR/Output/$DMG_NAME"
fi

echo ""
echo "=== Build complete ==="
echo "Output: $SCRIPT_DIR/Output/$DMG_NAME"
