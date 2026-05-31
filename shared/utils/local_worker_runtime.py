from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from urllib.parse import urljoin

WORKER_RUNTIME_DOCKER = "docker"
WORKER_RUNTIME_HYBRID_LOCAL_CPU = "hybrid-local-cpu"
WORKER_RUNTIME_HYBRID_LOCAL_MLX = "hybrid-local-mlx"
DEFAULT_LOCAL_WORKER_PORT = 8070
CONTAINER_SOURCE_ROOT = Path("/app/src")


def get_worker_runtime_mode() -> str:
    runtime = os.environ.get("HEARTHLIGHT_WORKER_RUNTIME", "").strip().lower()
    if runtime in {
        WORKER_RUNTIME_DOCKER,
        WORKER_RUNTIME_HYBRID_LOCAL_CPU,
        WORKER_RUNTIME_HYBRID_LOCAL_MLX,
    }:
        return runtime
    return WORKER_RUNTIME_DOCKER


def is_hybrid_local_cpu_runtime() -> bool:
    return get_worker_runtime_mode() == WORKER_RUNTIME_HYBRID_LOCAL_CPU


def is_hybrid_local_mlx_runtime() -> bool:
    return get_worker_runtime_mode() == WORKER_RUNTIME_HYBRID_LOCAL_MLX


def is_hybrid_local_runtime() -> bool:
    return get_worker_runtime_mode() in {
        WORKER_RUNTIME_HYBRID_LOCAL_CPU,
        WORKER_RUNTIME_HYBRID_LOCAL_MLX,
    }


def detect_host_machine() -> str:
    machine = platform.machine().lower()
    if platform.system() != "Darwin":
        return machine
    try:
        arm64_capable = subprocess.check_output(
            ["sysctl", "-n", "hw.optional.arm64"],
            text=True,
        ).strip()
        if arm64_capable == "1":
            return "arm64"
    except Exception:
        pass
    if machine not in {"x86_64", "i386"}:
        return machine
    try:
        detected = subprocess.check_output(["uname", "-m"], text=True).strip().lower()
        if detected:
            return detected
    except Exception:
        return machine
    return machine


def host_supports_mlx() -> bool:
    return platform.system() == "Darwin" and detect_host_machine() in {"arm64", "aarch64"}


def detect_default_worker_runtime(*, profile: str) -> str:
    if profile != "cpu":
        return WORKER_RUNTIME_DOCKER
    if host_supports_mlx():
        return WORKER_RUNTIME_HYBRID_LOCAL_MLX
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
