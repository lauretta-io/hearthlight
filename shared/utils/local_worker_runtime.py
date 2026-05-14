from __future__ import annotations

import os
import platform
from pathlib import Path
from urllib.parse import urljoin

WORKER_RUNTIME_DOCKER = "docker"
WORKER_RUNTIME_HYBRID_LOCAL_CPU = "hybrid-local-cpu"
DEFAULT_LOCAL_WORKER_PORT = 8070
CONTAINER_SOURCE_ROOT = Path("/app/src")


def get_worker_runtime_mode() -> str:
    runtime = os.environ.get("HEARTHLIGHT_WORKER_RUNTIME", "").strip().lower()
    if runtime in {WORKER_RUNTIME_DOCKER, WORKER_RUNTIME_HYBRID_LOCAL_CPU}:
        return runtime
    return WORKER_RUNTIME_DOCKER


def is_hybrid_local_cpu_runtime() -> bool:
    return get_worker_runtime_mode() == WORKER_RUNTIME_HYBRID_LOCAL_CPU


def detect_default_worker_runtime(*, profile: str) -> str:
    if profile != "cpu":
        return WORKER_RUNTIME_DOCKER
    if platform.system() == "Darwin":
        return WORKER_RUNTIME_HYBRID_LOCAL_CPU
    return WORKER_RUNTIME_DOCKER


def get_local_worker_base_url() -> str:
    configured = os.environ.get("HEARTHLIGHT_LOCAL_WORKER_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    host = os.environ.get("HEARTHLIGHT_LOCAL_WORKER_HOST", "host.docker.internal").strip() or "host.docker.internal"
    port = os.environ.get("HEARTHLIGHT_LOCAL_WORKER_PORT", str(DEFAULT_LOCAL_WORKER_PORT)).strip() or str(
        DEFAULT_LOCAL_WORKER_PORT
    )
    return f"http://{host}:{port}"


def build_local_worker_url(path: str) -> str:
    return urljoin(get_local_worker_base_url().rstrip("/") + "/", path.lstrip("/"))


def get_host_project_root() -> Path | None:
    raw = os.environ.get("HEARTHLIGHT_HOST_PROJECT_ROOT", "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def map_container_path_to_host(path_like: str | Path | None) -> str | None:
    if path_like is None:
        return None
    raw_path = Path(path_like)
    host_root = get_host_project_root()
    if host_root is None:
        return str(raw_path)
    try:
        relative = raw_path.relative_to(CONTAINER_SOURCE_ROOT)
    except ValueError:
        return str(raw_path)
    return str((host_root / relative).resolve())
