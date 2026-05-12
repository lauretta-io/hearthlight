from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Mapping

from shared.utils.docker_cli import build_docker_env, find_docker_binary

DEFAULT_DB_HOST = "localhost"
DEFAULT_DB_PORT = "5433"
DEFAULT_DB_USER = "postgres"
DEFAULT_DB_PASSWORD = "root"
DEFAULT_DB_NAME = "hearthlight"
DEFAULT_RABBIT_HOST = "localhost"
DEFAULT_RABBIT_PORT = "5673"

ROOT_DIR = Path(__file__).resolve().parents[1]
BASE_COMPOSE_PATH = ROOT_DIR / "docker-compose.yaml"


def _load_env_file(path: Path) -> dict[str, str]:
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        loaded[key.strip()] = value.strip().strip('"').strip("'")
    return loaded


def load_project_env_file(root_dir: Path = ROOT_DIR) -> dict[str, str]:
    return _load_env_file(root_dir / ".env")


def resolve_start_defaults(root_dir: Path = ROOT_DIR) -> dict[str, str]:
    env = load_project_env_file(root_dir)
    profile = str(env.get("HEARTHLIGHT_DEFAULT_PROFILE", "cpu")).strip().lower()
    if profile not in {"cpu", "cuda"}:
        profile = "cpu"
    use_cuda = profile == "cuda"
    return {
        "profile": profile,
        "detector_device": str(
            env.get("HEARTHLIGHT_DEFAULT_DETECTOR_DEVICE", "cuda" if use_cuda else "cpu")
        ).strip()
        or ("cuda" if use_cuda else "cpu"),
        "pose_device": str(
            env.get("HEARTHLIGHT_DEFAULT_POSE_DEVICE", "cuda" if use_cuda else "cpu")
        ).strip()
        or ("cuda" if use_cuda else "cpu"),
        "feature_device": str(
            env.get("HEARTHLIGHT_DEFAULT_FEATURE_DEVICE", "cuda:0" if use_cuda else "cpu")
        ).strip()
        or ("cuda:0" if use_cuda else "cpu"),
        "cuda_visible_devices": str(
            env.get("HEARTHLIGHT_DEFAULT_CUDA_VISIBLE_DEVICES", "all" if use_cuda else "")
        ).strip()
        or ("all" if use_cuda else ""),
    }


def _resolved_local_db_env(root_dir: Path = ROOT_DIR) -> dict[str, str]:
    env = os.environ.copy()
    env_file_values = _load_env_file(root_dir / ".env")
    for key, value in env_file_values.items():
        env.setdefault(key, value)

    env.setdefault("POSTGRES_USER", DEFAULT_DB_USER)
    env.setdefault("POSTGRES_PASSWORD", DEFAULT_DB_PASSWORD)
    env.setdefault("POSTGRES_DB", DEFAULT_DB_NAME)

    db_host = env.get("POSTGRES_HOST", "").strip().lower()
    db_port = env.get("POSTGRES_PORT", "").strip()
    host_port = env.get("POSTGRES_HOST_PORT", "").strip()

    # Resolve compose service names to host-local DB access for direct CLI resets.
    if db_host in {"", "db", "postgres"}:
        env["POSTGRES_HOST"] = env.get("POSTGRES_EXT_HOST", DEFAULT_DB_HOST)
        if host_port:
            env["POSTGRES_PORT"] = host_port
        elif not db_port or db_port == "5432":
            env["POSTGRES_PORT"] = env.get("POSTGRES_EXT_PORT", DEFAULT_DB_PORT)

    env.setdefault("POSTGRES_HOST", DEFAULT_DB_HOST)
    env.setdefault("POSTGRES_PORT", DEFAULT_DB_PORT)
    return env


def resolve_local_worker_env(root_dir: Path = ROOT_DIR) -> dict[str, str]:
    env = _resolved_local_db_env(root_dir)
    env_file_values = _load_env_file(root_dir / ".env")
    for key, value in env_file_values.items():
        env.setdefault(key, value)

    rabbit_host = env.get("RABBITMQ_HOST", "").strip().lower()
    rabbit_port = env.get("RABBITMQ_PORT", "").strip()
    rabbit_host_port = env.get("RABBITMQ_HOST_PORT", "").strip()
    if rabbit_host in {"", "rabbitmq"}:
        env["RABBITMQ_HOST"] = DEFAULT_RABBIT_HOST
    if rabbit_host_port:
        env["RABBITMQ_PORT"] = rabbit_host_port
    elif not rabbit_port:
        env["RABBITMQ_PORT"] = DEFAULT_RABBIT_PORT

    env["PYTHONPATH"] = str(root_dir)
    env["HEARTHLIGHT_CONFIG_PATH"] = str(root_dir / "shared" / "configs" / "config.yaml")
    env["HEARTHLIGHT_HOST_PROJECT_ROOT"] = str(root_dir)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _assert_tcp_reachable(
    host: str,
    port: str,
    timeout: float = 2.0,
    wait_seconds: float = 45.0,
) -> None:
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        try:
            with socket.create_connection((host, int(port)), timeout=timeout):
                return
        except Exception:
            time.sleep(1.0)

    raise RuntimeError(
        "Database is unreachable for direct reset-db execution. "
        f"Tried {host}:{port} for {int(wait_seconds)} seconds. "
        "Start the stack first (`hearthlight start`) or set "
        "POSTGRES_HOST/POSTGRES_PORT for host-accessible Postgres."
    )


def assert_local_worker_dependencies_reachable(
    root_dir: Path = ROOT_DIR,
    env_overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = resolve_local_worker_env(root_dir)
    if env_overrides:
        env.update(dict(env_overrides))
    _assert_tcp_reachable(env["POSTGRES_HOST"], env["POSTGRES_PORT"])
    _assert_tcp_reachable(env["RABBITMQ_HOST"], env["RABBITMQ_PORT"])
    return env


def run_local_reset_db(
    root_dir: Path = ROOT_DIR,
    env_overrides: Mapping[str, str] | None = None,
    allow_docker_fallback: bool = True,
) -> None:
    try:
        from shared.database.recreate_db import reset_db
    except ModuleNotFoundError as exc:
        if allow_docker_fallback:
            print(
                "Local reset-db dependencies are unavailable; "
                "falling back to `docker compose run --rm reset_db`."
            )
            run_docker_reset_db(root_dir)
            return
        raise RuntimeError(
            "Direct reset-db execution requires local Python dependencies "
            "(for example `sqlalchemy` and `psycopg2`). "
            "Install them, or rerun with `--docker`."
        ) from exc

    env = _resolved_local_db_env(root_dir)
    if env_overrides:
        env.update(dict(env_overrides))

    _assert_tcp_reachable(env["POSTGRES_HOST"], env["POSTGRES_PORT"])
    reset_db(env_overrides=env, output_dir=root_dir / "output")


def run_docker_reset_db(root_dir: Path = ROOT_DIR) -> None:
    docker_binary = find_docker_binary()
    if docker_binary is None:
        raise RuntimeError("Docker CLI not found. Install Docker Desktop or add docker to PATH.")
    command = [
        docker_binary,
        "compose",
        "-f",
        str(BASE_COMPOSE_PATH),
        "run",
        "--rm",
        "reset_db",
    ]
    subprocess.run(command, cwd=root_dir, env=build_docker_env(docker_binary), check=True)


def compose_status(root_dir: Path = ROOT_DIR, use_cuda: bool = False) -> int:
    from run.launcher import compose_command

    docker_binary = find_docker_binary()
    if docker_binary is None:
        raise SystemExit("Docker CLI not found. Install Docker Desktop or add docker to PATH.")

    command = compose_command(docker_binary, use_cuda) + [
        "ps",
        "db",
        "rabbitmq",
        "webapp",
        "ingestor",
        "reid",
        "association",
        "anomaly",
    ]
    return subprocess.call(command, cwd=root_dir, env=build_docker_env(docker_binary))
