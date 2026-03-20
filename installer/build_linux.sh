#!/usr/bin/env bash
# Build Linux AppImage for BOF Asset Decryptor
# Requirements: Python 3.10+, PyInstaller, appimagetool
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
VERSION=$(python3 -c "import sys; sys.path.insert(0,'$ROOT_DIR'); from bof_decryptor import __version__; print(__version__)")

echo "=== Building BOF Asset Decryptor v${VERSION} for Linux ==="

# Ensure icon exists
if [ ! -f "$ROOT_DIR/bof_decryptor/icon.png" ]; then
    echo "Generating icon..."
    pip3 install --quiet pillow 2>/dev/null || true
    python3 "$ROOT_DIR/generate_icon.py"
fi

# PyInstaller build (onedir mode for AppImage)
echo "Running PyInstaller..."
cd "$ROOT_DIR"
pip3 install --quiet pyinstaller 2>/dev/null || true
pyinstaller \
    --name "bof-decryptor" \
    --onedir \
    --add-data "$ROOT_DIR/bof_decryptor/icon.png:bof_decryptor" \
    --noconfirm \
    --clean \
    --distpath "$SCRIPT_DIR/build/dist" \
    --workpath "$SCRIPT_DIR/build/work" \
    --specpath "$SCRIPT_DIR/build" \
    "$ROOT_DIR/bof_decryptor/__main__.py"

DIST_DIR="$SCRIPT_DIR/build/dist/bof-decryptor"

# Build AppDir structure
APPDIR="$SCRIPT_DIR/build/BOF_Asset_Decryptor.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Copy PyInstaller output
cp -r "$DIST_DIR"/* "$APPDIR/usr/bin/"

# Icon
cp "$ROOT_DIR/bof_decryptor/icon.png" \
   "$APPDIR/usr/share/icons/hicolor/256x256/apps/bof-decryptor.png"
cp "$ROOT_DIR/bof_decryptor/icon.png" "$APPDIR/bof-decryptor.png"

# Desktop entry
cat > "$APPDIR/bof-decryptor.desktop" <<EOF
[Desktop Entry]
Name=BOF Asset Decryptor
Exec=bof-decryptor
Icon=bof-decryptor
Type=Application
Categories=Utility;
Comment=Decrypt and modify Barrels of Fun pinball game assets
EOF

# AppRun script
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/bash
SELF="$(readlink -f "$0")"
HERE="$(dirname "$SELF")"
exec "$HERE/usr/bin/bof-decryptor" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# Build AppImage
echo "Building AppImage..."
mkdir -p "$SCRIPT_DIR/Output"
APPIMAGE_NAME="BOF_Asset_Decryptor-v${VERSION}-x86_64.AppImage"

if command -v appimagetool &>/dev/null; then
    ARCH=x86_64 appimagetool "$APPDIR" "$SCRIPT_DIR/Output/$APPIMAGE_NAME"
else
    echo "appimagetool not found. Download from:"
    echo "  https://github.com/AppImage/appimagetool/releases"
    echo ""
    echo "AppDir is ready at: $APPDIR"
    echo "Run manually: ARCH=x86_64 appimagetool '$APPDIR' '$SCRIPT_DIR/Output/$APPIMAGE_NAME'"
    exit 1
fi

echo ""
echo "=== Build complete ==="
echo "Output: $SCRIPT_DIR/Output/$APPIMAGE_NAME"
