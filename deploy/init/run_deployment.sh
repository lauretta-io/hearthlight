#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

MODE="${1:-auto}"
API_PORT="${WEBAPP_API_HOST_PORT:-8000}"
API_BASE_URL="http://127.0.0.1:${API_PORT}"

find_docker_binary() {
  if command -v docker >/dev/null 2>&1; then
    command -v docker
    return 0
  fi
  if [[ -x "/Applications/Docker.app/Contents/Resources/bin/docker" ]]; then
    echo "/Applications/Docker.app/Contents/Resources/bin/docker"
    return 0
  fi
  return 1
}

resolve_mode() {
  if [[ "${MODE}" == "api" || "${MODE}" == "pipeline" ]]; then
    echo "${MODE}"
    return 0
  fi

  local uname_s uname_m
  uname_s="$(uname -s)"
  uname_m="$(uname -m)"
  if [[ "${uname_s}" == "Darwin" || "${uname_m}" == "arm64" || "${uname_m}" == "aarch64" ]]; then
    echo "api"
  else
    echo "pipeline"
  fi
}

wait_for_ready() {
  local attempts=60
  for _ in $(seq 1 "${attempts}"); do
    if curl -fsS "${API_BASE_URL}/readyz" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

check_docker_daemon() {
  if ! "${docker_binary}" info >/dev/null 2>&1; then
    echo "Docker daemon is not reachable. Start Docker Engine / Docker Desktop and retry." >&2
    exit 1
  fi
}

main() {
  local docker_binary
  docker_binary="$(find_docker_binary)"
  export PATH="$(dirname "${docker_binary}"):${PATH}"
  export RELOAD="${RELOAD:-}"

  local resolved_mode
  resolved_mode="$(resolve_mode)"

  echo "Using docker binary: ${docker_binary}"
  echo "Starting deployment in ${resolved_mode} mode"
  check_docker_daemon

  cd "${REPO_ROOT}"
  ./deploy/init/bootstrap_deployment.sh
  python3 scripts/container_preflight.py

  "${docker_binary}" compose up -d db rabbitmq reset_db webapp

  if ! wait_for_ready; then
    echo "Timed out waiting for ${API_BASE_URL}/readyz" >&2
    exit 1
  fi

  python3 deploy/init/seed_control_plane.py --base-url "${API_BASE_URL}"

  if [[ "${resolved_mode}" == "pipeline" ]]; then
    "${docker_binary}" compose --profile pipeline up -d ingestor reid association anomaly
  fi

  echo "Deployment is up."
  echo "Frontend: http://localhost:${WEBAPP_UI_HOST_PORT:-3000}"
  echo "API: ${API_BASE_URL}"
}

main "$@"
