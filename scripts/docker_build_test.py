#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.utils.docker_cli import build_docker_env, find_docker_binary


API_BUILD_SERVICES = ["rabbitmq", "webapp"]
CORE_BUILD_SERVICES = ["rabbitmq", "webapp", "ingestor", "reid", "association", "anomaly", "exporter"]
FOIA_BUILD_SERVICES = ["foia", "foia_webapp"]


def detect_default_mode() -> tuple[str, str]:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin" or machine in {"arm64", "aarch64"}:
        return (
            "api",
            f"defaulting to API-only builds on {system} {machine} because GPU images are not portable there",
        )
    return (
        "core",
        f"defaulting to core builds on {system} {machine}",
    )


def get_services(mode: str, extra_services: list[str]) -> list[str]:
    if extra_services:
        return extra_services
    if mode == "api":
        return API_BUILD_SERVICES
    if mode == "core":
        return CORE_BUILD_SERVICES
    if mode == "foia":
        return CORE_BUILD_SERVICES + FOIA_BUILD_SERVICES
    raise ValueError(f"unsupported mode {mode}")


def run_preflight() -> None:
    subprocess.run(
        [sys.executable, "scripts/container_preflight.py"],
        cwd=REPO_ROOT,
        check=True,
    )


def main() -> int:
    auto_mode, auto_reason = detect_default_mode()
    parser = argparse.ArgumentParser(
        description="Validate Docker Compose image builds for this repository"
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "api", "core", "foia"],
        default="auto",
        help="build scope: auto picks api on Apple Silicon/Darwin and core otherwise",
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

    mode = auto_mode if args.mode == "auto" else args.mode
    if args.mode == "auto":
        print(f"INFO: {auto_reason}")

    if not args.skip_preflight:
        print("INFO: running container preflight")
        run_preflight()

    services = get_services(mode, args.service)
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
    print("PASS: docker build validation succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
