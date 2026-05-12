#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SPEC_DIR="$ROOT_DIR/packaging/macos"
GENERATED_DIR="$SPEC_DIR/generated"
ICONSET_DIR="$GENERATED_DIR/Hearthlight.iconset"
ICON_SOURCE="$ROOT_DIR/frontend/public/hearthlight.png"
APP_SPEC="$SPEC_DIR/Hearthlight.spec"
HELPER_SPEC="$SPEC_DIR/hearthlight_helper.spec"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build"
PYTHON_BIN="${PYTHON_BIN:-python3}"

command -v sips >/dev/null || { echo "sips is required on macOS" >&2; exit 1; }
command -v iconutil >/dev/null || { echo "iconutil is required on macOS" >&2; exit 1; }
"$PYTHON_BIN" -c "import tkinter" >/dev/null 2>&1 || {
  echo "The selected Python interpreter does not provide tkinter, which is required for the packaged app UI." >&2
  exit 1
}

mkdir -p "$GENERATED_DIR"
rm -rf "$ICONSET_DIR"
mkdir -p "$ICONSET_DIR"

if [[ ! -f "$ICON_SOURCE" ]]; then
  echo "Missing icon source: $ICON_SOURCE" >&2
  exit 1
fi

echo "Generating macOS iconset..."
sips -z 16 16 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_16x16.png" >/dev/null
sips -z 32 32 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_32x32.png" >/dev/null
sips -z 64 64 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_128x128.png" >/dev/null
sips -z 256 256 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_256x256.png" >/dev/null
sips -z 512 512 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "$ICON_SOURCE" --out "$ICONSET_DIR/icon_512x512.png" >/dev/null
cp "$ICON_SOURCE" "$ICONSET_DIR/icon_512x512@2x.png"
iconutil -c icns "$ICONSET_DIR" -o "$GENERATED_DIR/Hearthlight.icns"

echo "Installing packaging dependencies..."
"$PYTHON_BIN" -m pip install ".[macos-app]"

echo "Cleaning previous build artifacts..."
rm -rf "$DIST_DIR/Hearthlight" "$DIST_DIR/Hearthlight.app" "$DIST_DIR/hearthlight-helper" "$BUILD_DIR/Hearthlight" "$BUILD_DIR/hearthlight_helper"

echo "Building console helper..."
"$PYTHON_BIN" -m PyInstaller --noconfirm --clean "$HELPER_SPEC"

echo "Building macOS app bundle..."
"$PYTHON_BIN" -m PyInstaller --noconfirm --clean "$APP_SPEC"

HELPER_BIN="$DIST_DIR/hearthlight-helper"
APP_MACOS_DIR="$DIST_DIR/Hearthlight.app/Contents/MacOS"
if [[ ! -x "$HELPER_BIN" ]]; then
  echo "Helper binary was not created at $HELPER_BIN" >&2
  exit 1
fi
if [[ ! -d "$APP_MACOS_DIR" ]]; then
  echo "App bundle was not created at $APP_MACOS_DIR" >&2
  exit 1
fi

cp "$HELPER_BIN" "$APP_MACOS_DIR/hearthlight-helper"
chmod +x "$APP_MACOS_DIR/hearthlight-helper"
codesign --force --deep --sign - "$DIST_DIR/Hearthlight.app"

echo "Built app bundle:"
echo "  $DIST_DIR/Hearthlight.app"
