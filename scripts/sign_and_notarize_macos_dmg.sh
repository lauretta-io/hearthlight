#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
APP_PATH="${1:-$DIST_DIR/Hearthlight.app}"
DMG_PATH="${2:-$DIST_DIR/Hearthlight.dmg}"

: "${APPLE_DEVELOPER_IDENTITY:?APPLE_DEVELOPER_IDENTITY is required}"
: "${APPLE_ID:?APPLE_ID is required}"
: "${APPLE_APP_SPECIFIC_PASSWORD:?APPLE_APP_SPECIFIC_PASSWORD is required}"
: "${APPLE_TEAM_ID:?APPLE_TEAM_ID is required}"

if [[ ! -d "$APP_PATH" ]]; then
  echo "Missing app bundle at $APP_PATH" >&2
  exit 1
fi

if [[ ! -f "$DMG_PATH" ]]; then
  echo "Missing DMG at $DMG_PATH" >&2
  exit 1
fi

echo "Signing app bundle..."
codesign --force --deep --options runtime --sign "$APPLE_DEVELOPER_IDENTITY" "$APP_PATH"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

echo "Signing DMG..."
codesign --force --sign "$APPLE_DEVELOPER_IDENTITY" "$DMG_PATH"

echo "Submitting DMG for notarization..."
xcrun notarytool submit "$DMG_PATH" \
  --apple-id "$APPLE_ID" \
  --password "$APPLE_APP_SPECIFIC_PASSWORD" \
  --team-id "$APPLE_TEAM_ID" \
  --wait

echo "Stapling notarization ticket..."
xcrun stapler staple "$APP_PATH"
xcrun stapler staple "$DMG_PATH"

echo "Signed and notarized:"
echo "  $APP_PATH"
echo "  $DMG_PATH"
