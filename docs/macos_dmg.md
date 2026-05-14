# macOS App Bundle

Hearthlight can be packaged for macOS as a signed `.app` inside a `.dmg`.

## What the app does

The packaged app is a bootstrap and control-plane manager. It supports:

- onboarding
- repo clone/update into `~/hearthlight`
- `.env` and config bootstrap
- Docker `db` / `rabbitmq` and optional `webapp`
- `reset-db`
- control-plane start/stop/status
- opening the dashboard

It does not embed the full runtime repo or promise packaged local worker/webcam runtime in v1.

## Local build

On macOS:

```bash
bash scripts/build_macos_app.sh
bash scripts/package_macos_dmg.sh
```

Artifacts:

- `dist/Hearthlight.app`
- `dist/Hearthlight.dmg`

Local verification:

```bash
codesign --verify --deep --strict --verbose=2 dist/Hearthlight.app
hdiutil verify dist/Hearthlight.dmg
spctl --assess --type execute --verbose=4 dist/Hearthlight.app
```

The build script:

- generates a `.icns` file from `frontend/public/hearthlight.png`
- builds a windowed `Hearthlight.app`
- builds a bundled `hearthlight-helper` console binary
- places the helper inside the app bundle so the UI can run onboarding and control-plane commands

## Signing and notarization

For official release artifacts:

```bash
export APPLE_DEVELOPER_IDENTITY="Developer ID Application: ..."
export APPLE_ID="..."
export APPLE_APP_SPECIFIC_PASSWORD="..."
export APPLE_TEAM_ID="..."
bash scripts/sign_and_notarize_macos_dmg.sh
```

This script:

- signs the app bundle
- signs the `.dmg`
- submits the `.dmg` to Apple notarization
- staples the notarization ticket to both the app bundle and the `.dmg`

Unsigned or ad-hoc signed local builds may pass `codesign --verify` but still be rejected by
`spctl` until they are signed with a Developer ID certificate and notarized.

## CI

GitHub Actions workflow:

- `.github/workflows/macos-dmg.yml`

**Release DMG:** push a **`v*`** tag so CI attaches `dist/Hearthlight.dmg` to that GitHub Release (match `pyproject.toml` / `frontend/package.json` to the version). Manual “Run workflow” only uploads Actions artifacts.

```bash
git tag -a v0.9.0 -m "v0.9.0"
git push origin v0.9.0
```

Expected secrets for signed/notarized releases:

- `APPLE_CERTIFICATE_P12_BASE64`
- `APPLE_CERTIFICATE_PASSWORD`
- `APPLE_DEVELOPER_IDENTITY`
- `APPLE_ID`
- `APPLE_APP_SPECIFIC_PASSWORD`
- `APPLE_TEAM_ID`
