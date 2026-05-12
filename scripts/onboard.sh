#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "Hearthlight shell onboarding"
echo "Workspace root: ${ROOT_DIR}"
echo "This wrapper runs the step-by-step Hearthlight onboarding flow, including .env setup for Telegram and Apple Messages."

exec "${PYTHON_BIN}" -m hearthlight onboard "$@"
