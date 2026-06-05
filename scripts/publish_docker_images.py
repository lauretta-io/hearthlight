#!/usr/bin/env python3

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.utils.docker_cli import build_docker_env, find_docker_binary
from shared.utils.image_variants import (
    IMAGE_VARIANTS,
    build_local_image_name,
    build_published_image_name,
    default_image_services_for_variant,
)


SERVICE_IMAGE_VARS = {
    "rabbitmq": "HEARTHLIGHT_RABBITMQ_IMAGE",
    "webapp": "HEARTHLIGHT_WEBAPP_IMAGE",
    "ingestor": "HEARTHLIGHT_INGESTOR_IMAGE",
    "association": "HEARTHLIGHT_ASSOCIATION_IMAGE",
    "anomaly": "HEARTHLIGHT_ANOMALY_IMAGE",
}

DEFAULT_SERVICES = list(SERVICE_IMAGE_VARS.keys())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build, tag, push Hearthlight service images, and optionally update .env to use them.",
    )
    parser.add_argument("--namespace", required=True, help="Docker Hub namespace/org, for example laurettaio")
    parser.add_argument("--tag", default="0.8.2", help="Published image tag")
    parser.add_argument(
        "--variant",
        choices=IMAGE_VARIANTS,
        default="cpu",
        help="Image variant to publish.",
    )
    parser.add_argument(
        "--service",
        action="append",
        choices=DEFAULT_SERVICES,
        default=[],
        help="Publish only the selected service. Repeat as needed.",
    )
    parser.add_argument("--skip-build", action="store_true", help="Skip docker compose build before tagging")
    parser.add_argument("--dry-run", action="store_true", help="Print the build/tag/push plan without executing it")
    parser.add_argument(
        "--write-env",
        metavar="PATH",
        help="Write the published image references into the given env file, for example .env",
    )
    parser.add_argument("--docker-binary", help="Override the docker binary path")
    return parser.parse_args()


def selected_services(args: argparse.Namespace) -> list[str]:
    return args.service or default_image_services_for_variant(args.variant)


def run(command: list[str], *, env: dict[str, str]) -> None:
    subprocess.run(command, cwd=REPO_ROOT, env=env, check=True)


def update_env_file(path: Path, updates: dict[str, str]) -> None:
    existing_lines = path.read_text().splitlines() if path.exists() else []
    remaining = dict(updates)
    rewritten: list[str] = []
    for line in existing_lines:
        if "=" not in line or line.lstrip().startswith("#"):
            rewritten.append(line)
            continue
        key, _, _value = line.partition("=")
        key = key.strip()
        if key in remaining:
            rewritten.append(f"{key}={remaining.pop(key)}")
        else:
            rewritten.append(line)
    if rewritten and rewritten[-1] != "":
        rewritten.append("")
    for key, value in updates.items():
        if key in remaining:
            rewritten.append(f"{key}={value}")
    path.write_text("\n".join(rewritten) + "\n")


def main() -> int:
    args = parse_args()
    docker_binary = args.docker_binary or find_docker_binary()
    if docker_binary is None:
        print("ERROR: docker CLI could not be found", file=sys.stderr)
        return 1

    services = selected_services(args)
    env = build_docker_env(docker_binary)
    env.setdefault("RELOAD", "")
    env["HEARTHLIGHT_IMAGE_VARIANT"] = args.variant

    if args.dry_run:
        print(f"INFO: namespace={args.namespace}")
        print(f"INFO: tag={args.tag}")
        print(f"INFO: variant={args.variant}")
        print(f"INFO: services={', '.join(services)}")
        if not args.skip_build:
            build_command = [docker_binary, "compose"]
            if args.variant == "cuda":
                build_command.extend(["-f", "docker-compose.yaml", "-f", "run/docker-compose.cuda.yaml"])
            build_command.extend(["build", *services])
            print("DRY RUN:", " ".join(build_command))
        for service in services:
            local_image = build_local_image_name(service, args.variant)
            remote_image = build_published_image_name(args.namespace, service, args.tag, args.variant)
            print("DRY RUN:", " ".join([docker_binary, "tag", local_image, remote_image]))
            print("DRY RUN:", " ".join([docker_binary, "push", remote_image]))
        if args.write_env:
            print(f"DRY RUN: would update {args.write_env}")
        return 0

    if not args.skip_build:
        build_command = [docker_binary, "compose"]
        if args.variant == "cuda":
            build_command.extend(["-f", str(REPO_ROOT / "docker-compose.yaml"), "-f", str(REPO_ROOT / "run" / "docker-compose.cuda.yaml")])
        build_command.extend(["build", *services])
        run(build_command, env=env)

    env_updates: dict[str, str] = {}
    for service in services:
        local_image = build_local_image_name(service, args.variant)
        remote_image = build_published_image_name(args.namespace, service, args.tag, args.variant)
        print(f"INFO: tagging {local_image} -> {remote_image}")
        run([docker_binary, "tag", local_image, remote_image], env=env)
        print(f"INFO: pushing {remote_image}")
        run([docker_binary, "push", remote_image], env=env)
        env_updates[SERVICE_IMAGE_VARS[service]] = remote_image

    if args.write_env:
        env_path = (REPO_ROOT / args.write_env).resolve() if not Path(args.write_env).is_absolute() else Path(args.write_env)
        update_env_file(env_path, env_updates)
        print(f"INFO: wrote published image refs to {env_path}")

    print("PASS: docker image publish completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
