#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

mkdir -p "${REPO_ROOT}/shared/configs"

if [[ ! -f "${REPO_ROOT}/.env" ]]; then
  cp "${REPO_ROOT}/deploy/seeds/runtime.env.seed" "${REPO_ROOT}/.env"
  echo "Created .env from deploy/seeds/runtime.env.seed"
fi

if [[ ! -f "${REPO_ROOT}/shared/configs/config.yaml" ]]; then
  cp "${REPO_ROOT}/shared/configs/example_config.yaml" "${REPO_ROOT}/shared/configs/config.yaml"
  echo "Created shared/configs/config.yaml from example_config.yaml"
fi

cp "${REPO_ROOT}/deploy/seeds/control_plane/model_bindings.seed.yaml" \
  "${REPO_ROOT}/shared/configs/model_bindings.yaml"
echo "Updated shared/configs/model_bindings.yaml from deployment seed"

echo "Bootstrap files are ready. Run deploy/init/seed_control_plane.py after db/reset_db is available."
