#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from importlib.util import find_spec
import platform
import re
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.utils.docker_cli import build_docker_env, find_docker_binary

COMPOSE_FILE = REPO_ROOT / "docker-compose.yaml"

CORE_BUILD_CONTEXTS = [
    "rabbitmq",
    "webapp",
    "ingestor",
    "reid",
    "association",
]

OPTIONAL_BUILD_CONTEXTS = [
    "FOIA",
]

CORE_REQUIRED_FILES = [
    ".env",
    "shared/configs/config.yaml",
]

OPTIONAL_REQUIRED_FILES = [
    "foia.env",
]

MISSING_FILE_HINTS = {
    ".env": "Copy example.env to .env and set database/RabbitMQ values for this machine.",
    "shared/configs/config.yaml": (
        "Copy shared/configs/example_config.yaml to shared/configs/config.yaml and replace "
        "placeholder camera sources before starting GPU-backed services."
    ),
    "foia.env": "Create foia.env only if you plan to run the optional FOIA profile.",
}


def check(condition: bool, message: str, failures: list[str], warnings: list[str], *, optional: bool = False) -> None:
    if condition:
        print(f"PASS: {message}")
        return
    prefix = "WARN" if optional else "FAIL"
    print(f"{prefix}: {message}")
    (warnings if optional else failures).append(message)


def parse_compose_paths(compose_text: str, key: str) -> list[str]:
    pattern = rf"^\s*{re.escape(key)}:\s+\./([^\s]+)\s*$"
    return re.findall(pattern, compose_text, flags=re.MULTILINE)


def main() -> int:
    failures: list[str] = []
    warnings: list[str] = []

    check(COMPOSE_FILE.exists(), "docker-compose.yaml exists", failures, warnings)
    compose_text = COMPOSE_FILE.read_text() if COMPOSE_FILE.exists() else ""

    docker_path = find_docker_binary()
    check(docker_path is not None, "docker CLI is installed", failures, warnings)

    if docker_path is not None:
        docker_compose_available = False
        try:
            result = subprocess.run(
                [docker_path, "compose", "version"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                env=build_docker_env(docker_path),
            )
            docker_compose_available = result.returncode == 0
        except Exception:
            docker_compose_available = False
        check(
            docker_compose_available,
            "docker compose plugin is available",
            failures,
            warnings,
        )

    discovered_builds = set(parse_compose_paths(compose_text, "build"))
    for context in CORE_BUILD_CONTEXTS:
        check(
            context in discovered_builds,
            f"compose references core build context ./{context}",
            failures,
            warnings,
        )
        check(
            (REPO_ROOT / context / "Dockerfile").exists(),
            f"./{context}/Dockerfile exists",
            failures,
            warnings,
        )

    for context in OPTIONAL_BUILD_CONTEXTS:
        if context in discovered_builds:
            check(
                (REPO_ROOT / context / "Dockerfile").exists(),
                f"./{context}/Dockerfile exists for optional FOIA services",
                failures,
                warnings,
                optional=True,
            )

    for rel_path in CORE_REQUIRED_FILES:
        exists = (REPO_ROOT / rel_path).exists()
        check(exists, f"{rel_path} exists", failures, warnings)
        if not exists and rel_path in MISSING_FILE_HINTS:
            print(f"INFO: {MISSING_FILE_HINTS[rel_path]}")

    package_available = find_spec("hearthlight_model_zoo") is not None
    check(
        package_available,
        "hearthlight_model_zoo Python package is importable",
        failures,
        warnings,
    )
    if not package_available:
        print(
            "INFO: Install service dependencies (for example from webapp/requirements.txt, "
            "ingestor/requirements.txt, or reid/requirements.txt) before running the stack."
        )

    for rel_path in OPTIONAL_REQUIRED_FILES:
        exists = (REPO_ROOT / rel_path).exists()
        check(
            exists,
            f"{rel_path} exists for optional FOIA services",
            failures,
            warnings,
            optional=True,
        )
        if not exists and rel_path in MISSING_FILE_HINTS:
            print(f"INFO: {MISSING_FILE_HINTS[rel_path]}")

    if compose_text:
        uses_nvidia_runtime = "runtime: nvidia" in compose_text
        uses_gpu_reservations = "gpus: all" in compose_text
        if uses_nvidia_runtime or uses_gpu_reservations:
            print("INFO: Compose declares NVIDIA access for GPU-backed services.")
            if platform.system() == "Darwin":
                check(
                    False,
                    "GPU-backed services require NVIDIA container runtime, which is not available under Docker Desktop on macOS",
                    failures,
                    warnings,
                    optional=True,
                )
        expected_model_ports = [
            "${WEBAPP_API_HOST_PORT:-8000}:8000",
            "${WEBAPP_UI_HOST_PORT:-3000}:3000",
        ]
        for port_mapping in expected_model_ports:
            check(
                port_mapping in compose_text,
                f"compose publishes model-control endpoint mapping {port_mapping}",
                failures,
                warnings,
            )
        if 'profiles: ["foia"]' in compose_text:
            print("INFO: FOIA services are gated behind the optional `foia` compose profile.")
        if 'profiles: ["pipeline"]' in compose_text:
            print("INFO: AI worker services are gated behind the optional `pipeline` compose profile.")

    print()
    print(f"Summary: {len(failures)} blocking issue(s), {len(warnings)} warning(s)")

    if failures:
        print("Container startup is not ready on this machine.")
        return 1

    print("Core container prerequisites look ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
