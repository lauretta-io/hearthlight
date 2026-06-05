from __future__ import annotations

import argparse
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from run.launcher import (  # noqa: E402
    build_interactive_selection,
    build_selection_from_args,
    detect_worker_runtime,
    prepare_local_images,
    print_model_inventory,
    start_stack,
    stop_stack,
)
from hearthlight.onboarding import run_onboarding  # noqa: E402
from hearthlight.runtime import (  # noqa: E402
    compose_status,
    resolve_start_defaults,
    run_docker_reset_db,
    run_local_reset_db,
)
from hearthlight.workspace import (  # noqa: E402
    LOCAL_EXECUTION_ENV,
    resolve_workspace,
    workspace_python_path,
)
from shared.utils.image_variants import IMAGE_VARIANTS  # noqa: E402

ASCII_LOGO = r"""
      /\        
     /  \    []
    /    \   []
   /      \  []
  /   /\   \
 /   /  \   \
/___/____\___\
|   \ /\ /   |
|    /  \    |
|   / /\ \   |
|__/ /  \ \__|
   (  __  )
    \(__)/
"""


def _print_cli_banner() -> None:
    print(ASCII_LOGO.rstrip())
    print("Hearthlight")
    print("")


def _add_common_start_args(parser: argparse.ArgumentParser) -> None:
    defaults = resolve_start_defaults(ROOT_DIR)
    parser.add_argument("--template", help="Config template to use (active, example, or saved config stem)")
    parser.add_argument(
        "--source-preset",
        help="Template to use for input cameras and zone blocks without changing the base runtime template",
    )
    parser.add_argument("--profile", choices=["cpu", "cuda"], default=defaults["profile"])
    parser.add_argument(
        "--worker-runtime",
        choices=["docker", "hybrid-local-cpu", "hybrid-local-mlx"],
        help="Worker runtime selection. Defaults to host-aware auto-detection.",
    )
    parser.add_argument("--detector", help="Detector model name")
    parser.add_argument("--tracker", help="Tracker name")
    parser.add_argument("--detector-device", help="Detector device override, for example cpu or cuda")
    parser.add_argument("--pose-model", help="Pose model name")
    parser.add_argument("--pose-device", help="Pose device override, for example cpu or cuda")
    parser.add_argument("--feature-extractor", help="Feature extractor model name")
    parser.add_argument("--feature-device", help="Feature extractor device override, for example cpu or cuda:0")
    parser.add_argument("--cuda-visible-devices", help="CUDA_VISIBLE_DEVICES value when --profile cuda")
    parser.add_argument("--reload", action="store_true", help="Set RELOAD=1 for compose services")
    reset_group = parser.add_mutually_exclusive_group()
    reset_group.add_argument(
        "--reset-db",
        dest="skip_reset_db",
        action="store_false",
        help="Run reset-db before startup.",
    )
    reset_group.add_argument(
        "--skip-reset-db",
        dest="skip_reset_db",
        action="store_true",
        help="Skip reset-db before startup. This is the default.",
    )
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
    parser.set_defaults(pose_enabled=None, show_video=None, skip_reset_db=True)


def _add_workspace_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workspace",
        help="Managed hearthlight workspace path. Defaults to saved onboarding workspace or HEARTHLIGHT_WORKSPACE.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Hearthlight CLI for passenger detection orchestration",
    )
    subparsers = parser.add_subparsers(dest="command")

    start_parser = subparsers.add_parser("start", help="Start the stack")
    _add_workspace_arg(start_parser)
    _add_common_start_args(start_parser)
    start_parser.add_argument("--interactive", action="store_true", help="Prompt for startup selections")

    stop_parser = subparsers.add_parser("stop", help="Stop the stack")
    _add_workspace_arg(stop_parser)
    stop_parser.add_argument(
        "--profile",
        choices=["cpu", "cuda"],
        default="cpu",
        help="Use the matching compose file set for shutdown",
    )

    reset_parser = subparsers.add_parser("reset-db", help="Reset the runtime database via direct function execution")
    _add_workspace_arg(reset_parser)
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
    _add_workspace_arg(status_parser)
    status_parser.add_argument(
        "--profile",
        choices=["cpu", "cuda"],
        default="cpu",
        help="Use the matching compose file set for status checks",
    )

    prepare_images_parser = subparsers.add_parser(
        "prepare-images",
        help="Build the system-appropriate local Docker image lane and optionally persist the variant",
    )
    _add_workspace_arg(prepare_images_parser)
    prepare_images_parser.add_argument(
        "--profile",
        choices=["cpu", "cuda"],
        help="Execution profile to prepare for. Defaults to the detected host-appropriate profile.",
    )
    prepare_images_parser.add_argument(
        "--worker-runtime",
        choices=["docker", "hybrid-local-cpu", "hybrid-local-mlx"],
        help="Worker runtime to prepare for. Defaults to the detected runtime for the selected profile.",
    )
    prepare_images_parser.add_argument(
        "--variant",
        choices=list(IMAGE_VARIANTS),
        help="Override the derived image variant directly.",
    )
    prepare_images_parser.add_argument(
        "--service",
        action="append",
        choices=["rabbitmq", "webapp", "ingestor", "association", "anomaly"],
        default=[],
        help="Build only the selected service image. Repeat as needed.",
    )
    prepare_images_parser.add_argument("--dry-run", action="store_true", help="Print the build plan without executing it")
    prepare_images_parser.add_argument(
        "--write-env",
        metavar="PATH",
        default=".env",
        help="Persist the selected HEARTHLIGHT_IMAGE_VARIANT into the env file. Defaults to .env",
    )

    onboard_parser = subparsers.add_parser("onboard", help="Run step-by-step local onboarding")
    onboard_parser.add_argument("--target-dir", help="Clone/install target directory. Defaults to ~/hearthlight.")
    onboard_parser.add_argument("--yes", action="store_true", help="Accept onboarding steps without prompting")
    onboard_parser.add_argument("--skip-system-packages", action="store_true", help="Skip system package checks")
    onboard_parser.add_argument("--skip-config-copy", action="store_true", help="Skip copying example config")
    onboard_parser.add_argument("--force-env", action="store_true", help="Overwrite .env from example.env")
    onboard_parser.add_argument(
        "--force-config-copy",
        action="store_true",
        help="Overwrite shared/configs/config.yaml from the example config",
    )
    onboard_parser.add_argument(
        "--skip-python-requirements",
        action="store_true",
        help="Skip installing requirements.txt files",
    )
    onboard_parser.add_argument(
        "--skip-notification-setup",
        action="store_true",
        help="Skip Telegram and Apple Messages onboarding prompts",
    )
    onboard_parser.add_argument("--skip-cuda-detection", action="store_true", help="Skip CPU/GPU default detection")
    onboard_parser.add_argument("--skip-infra-init", action="store_true", help="Skip starting Docker Postgres/RabbitMQ and reset-db")
    onboard_parser.add_argument("--start-webapp", action="store_true", help="Also start webapp and reverse proxy during onboarding")
    onboard_parser.add_argument(
        "--mount-default-models",
        action="store_true",
        help="Seed the mounted model inventory with the workspace default detector, tracker, heuristic filter, and anomaly detection models.",
    )
    onboard_parser.add_argument(
        "--mount-model",
        action="append",
        default=[],
        help=(
            "Mount a specific model into the central inventory. Repeat as needed. "
            "Accepts either MODEL_KEY or STAGE:MODEL_KEY, for example "
            "`--mount-model detector:builtin_yolox_s_cpu` or `--mount-model chatgpt_api_stage_2`."
        ),
    )
    onboard_parser.add_argument("--openai-api-key", help="API key to use when mounting ChatGPT/OpenAI-compatible Stage 2 models.")
    onboard_parser.add_argument("--openai-model-name", help="OpenAI model name string to use for Chatgpt Stage 2.")
    onboard_parser.add_argument("--anthropic-api-key", help="API key to use when mounting Claude Stage 2 models.")
    onboard_parser.add_argument("--anthropic-model-name", help="Anthropic model name string to use for Claude Stage 2.")
    onboard_parser.add_argument("--lm-studio-api-key", help="Optional API key to use when mounting LM Studio Stage 2 models.")
    onboard_parser.add_argument("--lm-studio-api-base-url", help="Base URL to use when mounting LM Studio Stage 2 models.")
    onboard_parser.add_argument("--lm-studio-model-name", help="Model name string to use for LM Studio Stage 2.")
    onboard_parser.add_argument("--lauretta-api-key", help="API key to use when mounting Lauretta-hosted Stage 2 models.")
    onboard_parser.add_argument("--lauretta-api-base-url", help="Base URL to use when mounting Lauretta-hosted Stage 2 models.")
    onboard_parser.add_argument("--lauretta-model-name", help="Model name string to use for Lauretta-hosted Stage 2.")

    list_models_parser = subparsers.add_parser("list-models", help="List discovered templates and model options")
    _add_workspace_arg(list_models_parser)
    dashboard_parser = subparsers.add_parser("dashboard", help="Open the dashboard in a browser")
    _add_workspace_arg(dashboard_parser)
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


def _proxy_to_workspace(workspace: Path, argv: list[str]) -> int:
    python_path = workspace_python_path(workspace)
    if not python_path.exists():
        print(
            f"Workspace virtualenv is missing at {python_path}. Run `hearthlight onboard --target-dir {workspace}` first.",
            file=sys.stderr,
        )
        return 1
    env = os.environ.copy()
    env[LOCAL_EXECUTION_ENV] = "1"
    env["HEARTHLIGHT_WORKSPACE"] = str(workspace)
    return subprocess.call([str(python_path), "-m", "hearthlight", *argv], cwd=workspace, env=env)


def _prepare_images_from_args(args) -> int:
    defaults = resolve_start_defaults(ROOT_DIR)
    profile = args.profile or defaults["profile"]
    detected_worker_runtime, _ = detect_worker_runtime(profile)
    worker_runtime = args.worker_runtime or detected_worker_runtime
    if args.variant:
        if args.variant == "cuda":
            profile = "cuda"
            worker_runtime = "docker"
        elif args.variant == "mlx":
            profile = "cpu"
            worker_runtime = "hybrid-local-mlx"
        else:
            profile = "cpu"
    return prepare_local_images(
        profile=profile,
        worker_runtime=worker_runtime,
        services=args.service,
        variant_override=args.variant,
        dry_run=args.dry_run,
        write_env=args.write_env,
    )


def main(argv: list[str] | None = None) -> int:
    _legacy_wrapper_notice()
    argv = list(argv) if argv is not None else sys.argv[1:]
    if not argv:
        argv = ["start", "--interactive"]
    _print_cli_banner()
    parser = build_parser()
    args = parser.parse_args(argv)

    command = args.command or "start"
    if os.environ.get(LOCAL_EXECUTION_ENV) != "1" and command != "onboard":
        workspace = resolve_workspace(getattr(args, "workspace", None))
        if workspace is None:
            print(
                "No managed hearthlight workspace is configured. Run `hearthlight onboard` first or pass --workspace.",
                file=sys.stderr,
            )
            return 1
        if workspace.resolve() != ROOT_DIR.resolve():
            return _proxy_to_workspace(workspace, argv)
    if command == "list-models":
        print_model_inventory()
        return 0
    if command == "onboard":
        return run_onboarding(args, ROOT_DIR)
    if command == "stop":
        return stop_stack(use_cuda=getattr(args, "profile", "cpu") == "cuda")
    if command == "status":
        return compose_status(ROOT_DIR, use_cuda=getattr(args, "profile", "cpu") == "cuda")
    if command == "prepare-images":
        return _prepare_images_from_args(args)
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

    interactive = args.command is None or getattr(args, "interactive", False)
    selection = build_interactive_selection() if interactive else build_selection_from_args(args)
    return start_stack(selection, dry_run=getattr(args, "dry_run", False))


if __name__ == "__main__":
    raise SystemExit(main())
