from __future__ import annotations

from pathlib import Path
import os
import shutil


KNOWN_DOCKER_PATHS = [
    "/Applications/Docker.app/Contents/Resources/bin/docker",
]


def find_docker_binary() -> str | None:
    docker_binary = shutil.which("docker")
    if docker_binary:
        return docker_binary
    for candidate in KNOWN_DOCKER_PATHS:
        if Path(candidate).exists():
            return candidate
    return None


def build_docker_env(docker_binary: str | None = None) -> dict[str, str]:
    env = os.environ.copy()
    resolved_binary = docker_binary or find_docker_binary()
    if resolved_binary is None:
        return env
    docker_dir = str(Path(resolved_binary).resolve().parent)
    current_path = env.get("PATH", "")
    path_parts = current_path.split(os.pathsep) if current_path else []
    if docker_dir not in path_parts:
        env["PATH"] = docker_dir + os.pathsep + current_path if current_path else docker_dir
    return env
