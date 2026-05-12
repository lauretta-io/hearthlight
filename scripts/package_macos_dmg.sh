#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
STAGING_DIR="$DIST_DIR/dmg-staging"
APP_PATH="$DIST_DIR/Hearthlight.app"
DMG_PATH="$DIST_DIR/Hearthlight.dmg"

if [[ ! -d "$APP_PATH" ]]; then
  echo "Missing app bundle at $APP_PATH. Run scripts/build_macos_app.sh first." >&2
  exit 1
fi

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"
cp -R "$APP_PATH" "$STAGING_DIR/"

rm -f "$DMG_PATH"
hdiutil create \
  -volname "Hearthlight" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

echo "Packaged DMG:"
echo "  $DMG_PATH"
