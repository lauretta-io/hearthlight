#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.utils.docker_cli import build_docker_env, find_docker_binary


FULL_BUILD_SERVICES = ["rabbitmq", "webapp", "ingestor", "reid", "association", "anomaly"]


def get_services(extra_services: list[str]) -> list[str]:
    if extra_services:
        return extra_services
    return FULL_BUILD_SERVICES


def run_preflight() -> None:
    subprocess.run(
        [sys.executable, "scripts/container_preflight.py"],
        cwd=REPO_ROOT,
        check=True,
    )


def run_import_smoke(docker_binary: str, services: list[str]) -> None:
    import_checks = {
        "webapp": [
            "hearthlight_model_zoo.feature_extractors",
        ],
        "ingestor": [
            "hearthlight_model_zoo.detectors",
            "hearthlight_model_zoo.trackers",
            "hearthlight_model_zoo.feature_extractors",
            "hearthlight_model_zoo.pose",
            "hearthlight_model_zoo.anomaly_detectors",
        ],
        "reid": [
            "hearthlight_model_zoo.reid",
        ],
    }
    env = build_docker_env(docker_binary)
    env.setdefault("RELOAD", "")
    for service in services:
        modules = import_checks.get(service)
        if not modules:
            continue
        module_csv = ", ".join(modules)
        print(f"INFO: import smoke for {service}: {module_csv}")
        code = "import " + "; import ".join(modules)
        subprocess.run(
            [docker_binary, "compose", "run", "--rm", service, "python", "-c", code],
            cwd=REPO_ROOT,
            check=True,
            env=env,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Docker Compose image builds for this repository"
    )
    parser.add_argument(
        "--service",
        action="append",
        default=[],
        help="override service selection with explicit compose service names",
    )
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--pull", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--docker-binary")
    args = parser.parse_args()

    docker_binary = args.docker_binary or find_docker_binary()
    if docker_binary is None:
        print("ERROR: docker CLI could not be found", file=sys.stderr)
        return 1

    if not args.skip_preflight:
        print("INFO: running container preflight")
        run_preflight()

    services = get_services(args.service)
    print(f"INFO: building services: {', '.join(services)}")

    command = [docker_binary, "compose", "build"]
    if args.pull:
        command.append("--pull")
    if args.no_cache:
        command.append("--no-cache")
    command.extend(services)

    env = build_docker_env(docker_binary)
    env.setdefault("RELOAD", "")
    subprocess.run(command, cwd=REPO_ROOT, check=True, env=env)
    run_import_smoke(docker_binary, services)
    print("PASS: docker build validation succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
