from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from run.launcher import (  # noqa: E402
    build_interactive_selection,
    build_selection_from_args,
    detect_run_mode,
    print_model_inventory,
    start_stack,
    stop_stack,
)
from hearthlight.runtime import compose_status, run_docker_reset_db, run_local_reset_db  # noqa: E402


def _add_common_start_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--template", help="Config template to use (active, example, or saved config stem)")
    parser.add_argument(
        "--source-preset",
        help="Template to use for input cameras and zone blocks without changing the base runtime template",
    )
    parser.add_argument(
        "--mode",
        choices=["api", "pipeline"],
        help="Service startup mode. Defaults to host-aware auto-detection or HEARTHLIGHT_DOCKER_MODE.",
    )
    parser.add_argument("--profile", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--detector", help="Detector model name")
    parser.add_argument("--tracker", help="Tracker name")
    parser.add_argument("--detector-device", help="Detector device override, for example cpu or cuda")
    parser.add_argument("--pose-model", help="Pose model name")
    parser.add_argument("--pose-device", help="Pose device override, for example cpu or cuda")
    parser.add_argument("--feature-extractor", help="Feature extractor model name")
    parser.add_argument("--feature-device", help="Feature extractor device override, for example cpu or cuda:0")
    parser.add_argument("--cuda-visible-devices", help="CUDA_VISIBLE_DEVICES value when --profile cuda")
    parser.add_argument("--reload", action="store_true", help="Set RELOAD=1 for compose services")
    parser.add_argument("--skip-reset-db", action="store_true", help="Skip reset-db before startup")
    parser.add_argument("--open-dashboard", action="store_true", help="Open localhost:3000 when ready")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write and print the effective config without starting docker compose",
    )
    parser.add_argument("--pose-enabled", dest="pose_enabled", action="store_true", help="Enable pose estimation")
    parser.add_argument("--pose-disabled", dest="pose_enabled", action="store_false", help="Disable pose estimation")
    parser.add_argument("--show-video", dest="show_video", action="store_true", help="Enable local video windows")
    parser.add_argument("--hide-video", dest="show_video", action="store_false", help="Disable local video windows")
    parser.set_defaults(pose_enabled=None, show_video=None)


def build_parser() -> argparse.ArgumentParser:
    detected_run_mode, detected_reason = detect_run_mode()
    parser = argparse.ArgumentParser(
        description=(
            f"Hearthlight CLI for passenger detection orchestration "
            f"({detected_reason}; default mode={detected_run_mode})"
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    start_parser = subparsers.add_parser("start", help="Start the stack")
    _add_common_start_args(start_parser)
    start_parser.add_argument("--interactive", action="store_true", help="Prompt for startup selections")

    stop_parser = subparsers.add_parser("stop", help="Stop the stack")
    stop_parser.add_argument(
        "--profile",
        choices=["cpu", "cuda"],
        default="cpu",
        help="Use the matching compose file set for shutdown",
    )

    reset_parser = subparsers.add_parser("reset-db", help="Reset the runtime database via direct function execution")
    reset_parser.add_argument(
        "--docker",
        action="store_true",
        help="Use docker compose reset-db service instead of direct host function execution",
    )
    reset_parser.add_argument("--postgres-host", help="Override POSTGRES_HOST")
    reset_parser.add_argument("--postgres-port", help="Override POSTGRES_PORT")
    reset_parser.add_argument("--postgres-user", help="Override POSTGRES_USER")
    reset_parser.add_argument("--postgres-password", help="Override POSTGRES_PASSWORD")
    reset_parser.add_argument("--postgres-db", help="Override POSTGRES_DB")

    status_parser = subparsers.add_parser("status", help="Show compose service status")
    status_parser.add_argument(
        "--profile",
        choices=["cpu", "cuda"],
        default="cpu",
        help="Use the matching compose file set for status checks",
    )

    subparsers.add_parser("list-models", help="List discovered templates and model options")
    subparsers.add_parser("dashboard", help="Open the dashboard in a browser")
    subparsers.add_parser("gui", help="Open the legacy Tk launcher")
    return parser


def _legacy_wrapper_notice() -> None:
    if os.environ.get("HEARTHLIGHT_LEGACY_WRAPPER") == "1":
        print(
            "[deprecation] run/run.py is a compatibility wrapper. "
            "Use `python3 -m hearthlight <command>` (or installed `hearthlight`) instead.",
            file=sys.stderr,
        )


def _reset_db_from_args(args) -> int:
    overrides: dict[str, str] = {}
    if args.postgres_host:
        overrides["POSTGRES_HOST"] = args.postgres_host
    if args.postgres_port:
        overrides["POSTGRES_PORT"] = args.postgres_port
    if args.postgres_user:
        overrides["POSTGRES_USER"] = args.postgres_user
    if args.postgres_password:
        overrides["POSTGRES_PASSWORD"] = args.postgres_password
    if args.postgres_db:
        overrides["POSTGRES_DB"] = args.postgres_db

    try:
        if args.docker:
            run_docker_reset_db(ROOT_DIR)
        else:
            run_local_reset_db(ROOT_DIR, env_overrides=overrides or None)
    except Exception as exc:
        print(f"reset-db failed: {exc}", file=sys.stderr)
        return 1

    print("reset-db completed successfully")
    return 0


def main(argv: list[str] | None = None) -> int:
    _legacy_wrapper_notice()
    parser = build_parser()
    args = parser.parse_args(argv)

    command = args.command or "start"
    if command == "list-models":
        print_model_inventory()
        return 0
    if command == "stop":
        return stop_stack(use_cuda=getattr(args, "profile", "cpu") == "cuda")
    if command == "status":
        return compose_status(ROOT_DIR, use_cuda=getattr(args, "profile", "cpu") == "cuda")
    if command == "reset-db":
        return _reset_db_from_args(args)
    if command == "dashboard":
        dashboard_port = os.environ.get("WEBAPP_UI_HOST_PORT", "3000")
        webbrowser.open(f"http://localhost:{dashboard_port}")
        return 0
    if command == "gui":
        from run.gui_launcher import main as gui_main

        gui_main()
        return 0

    interactive = args.command is None or args.interactive
    selection = build_interactive_selection() if interactive else build_selection_from_args(args)
    return start_stack(selection, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
