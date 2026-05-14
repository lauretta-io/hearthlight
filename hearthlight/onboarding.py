from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path

from shared.utils.docker_cli import build_docker_env, find_docker_binary

from .workspace import (
    DEFAULT_REPO_BRANCH,
    DEFAULT_REPO_URL,
    DEFAULT_WORKSPACE_PATH,
    LOCAL_EXECUTION_ENV,
    save_default_workspace,
    workspace_python_path,
)

REQUIREMENT_PATHS = (
    Path("webapp/requirements.txt"),
    Path("ingestor/requirements.txt"),
    Path("reid/requirements.txt"),
    Path("anomaly/requirements.txt"),
    Path("association/requirements.txt"),
)


@dataclass(frozen=True)
class SystemPackagePlan:
    manager: str | None
    packages: tuple[str, ...]
    command: tuple[str, ...] | None
    missing_components: tuple[str, ...]


@dataclass(frozen=True)
class RuntimeProfileRecommendation:
    profile: str
    detector_device: str
    pose_device: str
    feature_extractor_device: str
    cuda_visible_devices: str
    reason: str


@dataclass(frozen=True)
class DockerInfraPlan:
    services: tuple[str, ...]
    started: bool


def check_host_tools(require_docker: bool = True) -> list[str]:
    missing: list[str] = []
    if shutil.which("git") is None:
        missing.append("git")
    if sys.version_info < (3, 10):
        missing.append("python>=3.10")
    if require_docker:
        docker_binary = find_docker_binary()
        if docker_binary is None:
            missing.append("docker")
        else:
            try:
                subprocess.run(
                    [docker_binary, "compose", "version"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=build_docker_env(docker_binary),
                )
            except Exception:
                missing.append("docker compose")
    return missing


def resolve_bootstrap_python() -> str:
    if not getattr(sys, "frozen", False):
        return sys.executable
    python3 = shutil.which("python3")
    if python3:
        return python3
    python = shutil.which("python")
    if python:
        return python
    raise RuntimeError(
        "A host Python interpreter is required to create the managed workspace virtualenv. "
        "Install Python 3 and rerun onboarding."
    )


def _prompt_yes_no(question: str, *, default: bool, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    prompt = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{question} [{prompt}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Please answer yes or no.")


def _load_env_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text().splitlines()


def _load_env_assignments(path: Path) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for line in _load_env_file(path):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        assignments[key.strip()] = value.strip()
    return assignments


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _write_env_assignments(path: Path, assignments: dict[str, str]) -> None:
    lines = _load_env_file(path)
    rendered = {key: f"{key}={value}" for key, value in assignments.items()}
    seen: set[str] = set()
    updated_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            updated_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in rendered:
            updated_lines.append(rendered[key])
            seen.add(key)
        else:
            updated_lines.append(line)

    if updated_lines and updated_lines[-1].strip():
        updated_lines.append("")
    for key in assignments:
        if key not in seen:
            updated_lines.append(rendered[key])

    path.write_text("\n".join(updated_lines).rstrip() + "\n")


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def _prompt_text(question: str, *, default: str = "") -> str:
    rendered_default = f" [{default}]" if default else ""
    raw = input(f"{question}{rendered_default}: ").strip()
    if not raw:
        return default
    return raw


def _python_headers_available() -> bool:
    include_dir = sysconfig.get_config_var("INCLUDEPY")
    if include_dir and Path(include_dir).exists():
        return True
    return shutil.which("python3-config") is not None


def _libpq_available() -> bool:
    return shutil.which("pg_config") is not None


def detect_system_package_plan() -> SystemPackagePlan:
    missing_components: list[str] = []
    if not _libpq_available():
        missing_components.append("libpq / pg_config")
    if not _python_headers_available():
        missing_components.append("python headers")

    if not missing_components:
        return SystemPackagePlan(
            manager=None,
            packages=(),
            command=None,
            missing_components=(),
        )

    system = platform.system()
    if system == "Darwin":
        manager = "brew" if shutil.which("brew") else None
        packages = ("postgresql", "python", "pkg-config")
        command = ("brew", "install", *packages) if manager else None
        return SystemPackagePlan(manager, packages, command, tuple(missing_components))

    if shutil.which("apt-get"):
        packages = ("libpq-dev", "python3-dev", "pkg-config")
        return SystemPackagePlan(
            "apt-get",
            packages,
            ("sudo", "apt-get", "install", "-y", *packages),
            tuple(missing_components),
        )

    if shutil.which("dnf"):
        packages = ("postgresql-devel", "python3-devel", "pkgconf-pkg-config")
        return SystemPackagePlan(
            "dnf",
            packages,
            ("sudo", "dnf", "install", "-y", *packages),
            tuple(missing_components),
        )

    if shutil.which("yum"):
        packages = ("postgresql-devel", "python3-devel", "pkgconfig")
        return SystemPackagePlan(
            "yum",
            packages,
            ("sudo", "yum", "install", "-y", *packages),
            tuple(missing_components),
        )

    return SystemPackagePlan(None, (), None, tuple(missing_components))


def detect_runtime_profile_recommendation() -> RuntimeProfileRecommendation:
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is not None:
        try:
            result = subprocess.run(
                [nvidia_smi, "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                check=True,
            )
            gpu_names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            if gpu_names:
                return RuntimeProfileRecommendation(
                    profile="cuda",
                    detector_device="cuda",
                    pose_device="cuda",
                    feature_extractor_device="cuda:0",
                    cuda_visible_devices="all",
                    reason=f"detected NVIDIA GPU via nvidia-smi: {', '.join(gpu_names)}",
                )
        except Exception:
            pass

    return RuntimeProfileRecommendation(
        profile="cpu",
        detector_device="cpu",
        pose_device="cpu",
        feature_extractor_device="cpu",
        cuda_visible_devices="",
        reason="no usable NVIDIA CUDA runtime detected; defaulting to CPU models",
    )


def ensure_workspace_clone(
    target_dir: Path,
    *,
    repo_url: str = DEFAULT_REPO_URL,
    branch: str = DEFAULT_REPO_BRANCH,
) -> tuple[Path, bool]:
    target_dir = target_dir.expanduser()
    if not target_dir.exists():
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        _run(
            ["git", "clone", "--branch", branch, repo_url, str(target_dir)],
            cwd=target_dir.parent,
        )
        return target_dir.resolve(), True

    git_dir = target_dir / ".git"
    if not git_dir.exists():
        raise RuntimeError(f"{target_dir} already exists and is not a git checkout")

    try:
        _run(["git", "-C", str(target_dir), "fetch", "origin", branch], cwd=target_dir)
        _run(["git", "-C", str(target_dir), "pull", "--ff-only", "origin", branch], cwd=target_dir)
    except subprocess.CalledProcessError:
        print("   Existing workspace is not fast-forward clean; leaving current checkout in place.")
    return target_dir.resolve(), False


def ensure_virtualenv(workspace: Path) -> Path:
    python_path = workspace_python_path(workspace)
    if python_path.exists():
        return python_path
    bootstrap_python = resolve_bootstrap_python()
    _run([bootstrap_python, "-m", "venv", str(workspace / ".venv")], cwd=workspace)
    return python_path


def copy_example_env(workspace: Path, *, force: bool = False) -> tuple[Path, bool]:
    example_path = workspace / "example.env"
    env_path = workspace / ".env"
    if not example_path.exists():
        raise RuntimeError(f"Missing environment template at {example_path}")
    if env_path.exists() and not force:
        return env_path, False
    shutil.copyfile(example_path, env_path)
    return env_path, True


def copy_example_config(root_dir: Path, *, force: bool = False) -> tuple[Path, bool]:
    config_dir = root_dir / "shared" / "configs"
    example_path = config_dir / "example_config.yaml"
    active_path = config_dir / "config.yaml"
    if not example_path.exists():
        raise RuntimeError(f"Missing example config at {example_path}")
    if active_path.exists() and not force:
        return active_path, False
    shutil.copyfile(example_path, active_path)
    return active_path, True


def apply_runtime_profile_defaults(config_path: Path, recommendation: RuntimeProfileRecommendation) -> None:
    from run.launcher import set_nested_scalar

    text = config_path.read_text()
    text = set_nested_scalar(text, ["rtdetr"], "device", recommendation.detector_device)
    text = set_nested_scalar(text, ["pose"], "device", recommendation.pose_device)
    text = set_nested_scalar(
        text,
        ["feature_extractor"],
        "device",
        recommendation.feature_extractor_device,
    )
    config_path.write_text(text)


def write_runtime_profile_env_defaults(root_dir: Path, recommendation: RuntimeProfileRecommendation) -> Path:
    env_path = root_dir / ".env"
    _write_env_assignments(
        env_path,
        {
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "root",
            "POSTGRES_DB": "hearthlight",
            "POSTGRES_HOST": "db",
            "POSTGRES_PORT": "5432",
            "POSTGRES_EXT_HOST": "localhost",
            "POSTGRES_EXT_PORT": "5433",
            "POSTGRES_HOST_PORT": "5433",
            "RABBITMQ_HOST": "rabbitmq",
            "RABBITMQ_PORT": "5672",
            "RABBITMQ_HOST_PORT": "5673",
            "RABBITMQ_MANAGEMENT_HOST_PORT": "15672",
            "RABBITMQ_EXCHANGE": "test",
            "WEBAPP_API_HOST_PORT": "8000",
            "WEBAPP_UI_HOST_PORT": "3000",
            "RESOURCE_DISK_THRESHOLD_PERCENT": "100",
            "HEARTHLIGHT_DEFAULT_PROFILE": recommendation.profile,
            "HEARTHLIGHT_DEFAULT_DETECTOR_DEVICE": recommendation.detector_device,
            "HEARTHLIGHT_DEFAULT_POSE_DEVICE": recommendation.pose_device,
            "HEARTHLIGHT_DEFAULT_FEATURE_DEVICE": recommendation.feature_extractor_device,
            "HEARTHLIGHT_DEFAULT_CUDA_VISIBLE_DEVICES": recommendation.cuda_visible_devices,
        },
    )
    return env_path


def write_notification_env_defaults(root_dir: Path) -> Path:
    env_path = root_dir / ".env"
    _write_env_assignments(
        env_path,
        {
            "TELEGRAM_TRIGGER_SUBSCRIPTION_ENABLED": "false",
            "TELEGRAM_TRIGGER_SUBSCRIPTION_LABEL": "Telegram Trigger Alerts",
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_CHAT_ID": "",
            "APPLE_MESSAGES_TRIGGER_SUBSCRIPTION_ENABLED": "false",
            "APPLE_MESSAGES_TRIGGER_SUBSCRIPTION_LABEL": "Apple Messages Trigger Alerts",
            "APPLE_MESSAGES_RECIPIENT": "",
            "APPLE_MESSAGES_SERVICE": "iMessage",
        },
    )
    return env_path


def configure_notification_env_interactively(root_dir: Path, *, assume_yes: bool) -> Path:
    env_path = write_notification_env_defaults(root_dir)
    if assume_yes:
        return env_path

    assignments = _load_env_assignments(env_path)
    updates: dict[str, str] = {}

    existing_telegram = bool(assignments.get("TELEGRAM_BOT_TOKEN") and assignments.get("TELEGRAM_CHAT_ID"))
    if _prompt_yes_no("   Configure Telegram trigger notifications?", default=existing_telegram, assume_yes=False):
        label = _prompt_text(
            "   Telegram subscription label",
            default=assignments.get("TELEGRAM_TRIGGER_SUBSCRIPTION_LABEL", "Telegram Trigger Alerts"),
        )
        bot_token = _prompt_text(
            "   Telegram bot token",
            default=assignments.get("TELEGRAM_BOT_TOKEN", ""),
        )
        chat_id = _prompt_text(
            "   Telegram chat ID",
            default=assignments.get("TELEGRAM_CHAT_ID", ""),
        )
        updates.update(
            {
                "TELEGRAM_TRIGGER_SUBSCRIPTION_LABEL": label,
                "TELEGRAM_BOT_TOKEN": bot_token,
                "TELEGRAM_CHAT_ID": chat_id,
                "TELEGRAM_TRIGGER_SUBSCRIPTION_ENABLED": "true" if bot_token and chat_id else "false",
            }
        )

    apple_supported = platform.system() == "Darwin"
    existing_apple = bool(assignments.get("APPLE_MESSAGES_RECIPIENT"))
    if not apple_supported:
        print("   Apple Messages setup is skipped on non-macOS hosts.")
    elif _prompt_yes_no("   Configure Apple Messages trigger notifications?", default=existing_apple, assume_yes=False):
        label = _prompt_text(
            "   Apple Messages subscription label",
            default=assignments.get("APPLE_MESSAGES_TRIGGER_SUBSCRIPTION_LABEL", "Apple Messages Trigger Alerts"),
        )
        recipient_handle = _prompt_text(
            "   Apple Messages recipient handle (phone number or email)",
            default=assignments.get("APPLE_MESSAGES_RECIPIENT", ""),
        )
        service = _prompt_text(
            "   Apple Messages service (iMessage or SMS)",
            default=assignments.get("APPLE_MESSAGES_SERVICE", "iMessage"),
        )
        service = service if service in {"iMessage", "SMS"} else "iMessage"
        updates.update(
            {
                "APPLE_MESSAGES_TRIGGER_SUBSCRIPTION_LABEL": label,
                "APPLE_MESSAGES_RECIPIENT": recipient_handle,
                "APPLE_MESSAGES_SERVICE": service,
                "APPLE_MESSAGES_TRIGGER_SUBSCRIPTION_ENABLED": "true" if recipient_handle else "false",
            }
        )

    if updates:
        _write_env_assignments(env_path, updates)
    return env_path


def sync_notification_subscriptions_from_env(root_dir: Path) -> list[str]:
    from shared.database.database import SessionLocal, reset_engine
    from shared.models import SQLModels
    from shared.utils.connector_endpoints import (
        CONNECTOR_KEY_APPLE_MESSAGES,
        CONNECTOR_KEY_TELEGRAM,
        set_connector_endpoint_payload,
    )
    from shared.utils.apple_messages_notifications import ensure_apple_message_subscription_tables
    from shared.utils.telegram_notifications import ensure_telegram_subscription_tables

    env_path = root_dir / ".env"
    assignments = _load_env_assignments(env_path)
    messages: list[str] = []
    host_env = {
        "POSTGRES_USER": assignments.get("POSTGRES_USER", ""),
        "POSTGRES_PASSWORD": assignments.get("POSTGRES_PASSWORD", ""),
        "POSTGRES_DB": assignments.get("POSTGRES_DB", ""),
        "POSTGRES_HOST": assignments.get("POSTGRES_EXT_HOST") or assignments.get("POSTGRES_HOST", ""),
        "POSTGRES_PORT": assignments.get("POSTGRES_EXT_PORT") or assignments.get("POSTGRES_PORT", ""),
    }
    os.environ.update(host_env)
    reset_engine()
    with SessionLocal() as db:
        telegram_enabled = _parse_bool(assignments.get("TELEGRAM_TRIGGER_SUBSCRIPTION_ENABLED"), default=False)
        telegram_bot_token = assignments.get("TELEGRAM_BOT_TOKEN", "")
        telegram_chat_id = assignments.get("TELEGRAM_CHAT_ID", "")
        if telegram_enabled and telegram_bot_token and telegram_chat_id:
            ensure_telegram_subscription_tables()
            label = assignments.get("TELEGRAM_TRIGGER_SUBSCRIPTION_LABEL", "Telegram Trigger Alerts").strip() or "Telegram Trigger Alerts"
            row = (
                db.query(SQLModels.ConnectorEndpoint)
                .filter_by(connector_key=CONNECTOR_KEY_TELEGRAM, label=label, is_deleted=False)
                .first()
            )
            if row is None:
                row = SQLModels.ConnectorEndpoint()
                db.add(row)
            set_connector_endpoint_payload(
                row,
                connector_key=CONNECTOR_KEY_TELEGRAM,
                label=label,
                enabled=True,
                config={
                    "bot_token": telegram_bot_token,
                    "chat_id": telegram_chat_id,
                },
                delivery_capabilities=["text"],
            )
            messages.append(f"Telegram: {label}")

        apple_enabled = _parse_bool(assignments.get("APPLE_MESSAGES_TRIGGER_SUBSCRIPTION_ENABLED"), default=False)
        apple_recipient = assignments.get("APPLE_MESSAGES_RECIPIENT", "")
        if apple_enabled and apple_recipient:
            ensure_apple_message_subscription_tables()
            label = assignments.get("APPLE_MESSAGES_TRIGGER_SUBSCRIPTION_LABEL", "Apple Messages Trigger Alerts").strip() or "Apple Messages Trigger Alerts"
            row = (
                db.query(SQLModels.ConnectorEndpoint)
                .filter_by(connector_key=CONNECTOR_KEY_APPLE_MESSAGES, label=label, is_deleted=False)
                .first()
            )
            if row is None:
                row = SQLModels.ConnectorEndpoint()
                db.add(row)
            service = assignments.get("APPLE_MESSAGES_SERVICE", "iMessage")
            set_connector_endpoint_payload(
                row,
                connector_key=CONNECTOR_KEY_APPLE_MESSAGES,
                label=label,
                enabled=True,
                config={
                    "recipient_handle": apple_recipient,
                    "service": service if service in {"iMessage", "SMS"} else "iMessage",
                },
                delivery_capabilities=["text"],
            )
            messages.append(f"Apple Messages: {label}")

        if messages:
            db.commit()
        else:
            db.rollback()
    return messages


def install_python_requirements(root_dir: Path, *, python_executable: str) -> None:
    _run([python_executable, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], cwd=root_dir)
    for relative_path in REQUIREMENT_PATHS:
        requirement_path = root_dir / relative_path
        if not requirement_path.exists():
            continue
        _run(
            [python_executable, "-m", "pip", "install", "-r", str(requirement_path)],
            cwd=root_dir,
        )
    _run([python_executable, "-m", "pip", "install", "-e", str(root_dir)], cwd=root_dir)


def start_docker_infra(workspace: Path, *, start_webapp: bool) -> DockerInfraPlan:
    docker_binary = find_docker_binary()
    if docker_binary is None:
        raise RuntimeError("Docker CLI not found. Install Docker Desktop or add docker to PATH.")
    env = build_docker_env(docker_binary)
    env.setdefault("RELOAD", "")
    services = ["db", "rabbitmq"]
    if start_webapp:
        services.extend(["webapp", "reverse_proxy"])
    _run([docker_binary, "compose", "up", "-d", *services], cwd=workspace, env=env)
    return DockerInfraPlan(services=tuple(services), started=True)


def run_workspace_reset_db(workspace: Path, python_executable: Path) -> None:
    env = os.environ.copy()
    env[LOCAL_EXECUTION_ENV] = "1"
    env["HEARTHLIGHT_WORKSPACE"] = str(workspace)
    _run([str(python_executable), "-m", "hearthlight", "reset-db", "--docker", "--workspace", str(workspace)], cwd=workspace, env=env)


def run_onboarding(args, root_dir: Path) -> int:
    print("Hearthlight onboarding")
    print("")

    target_dir = Path(getattr(args, "target_dir", "") or DEFAULT_WORKSPACE_PATH).expanduser()

    print("1. Host tools")
    missing_tools = check_host_tools(require_docker=not args.skip_infra_init)
    if missing_tools:
        raise RuntimeError("Missing required host tools: " + ", ".join(missing_tools))
    print("   Required host tools are available.")
    print("")

    if not args.skip_system_packages:
        print("2. System packages")
        plan = detect_system_package_plan()
        if not plan.missing_components:
            print("   System packages: already available")
        else:
            print("   Missing components: " + ", ".join(plan.missing_components))
            if plan.command is None:
                print("   No supported package-manager command was detected. Install the missing components manually.")
            else:
                print("   Suggested command: " + " ".join(plan.command))
                if _prompt_yes_no("   Run the system package install command now?", default=False, assume_yes=args.yes):
                    subprocess.run(list(plan.command), cwd=root_dir, check=True)
                    print("   System package install completed.")
        print("")

    print("3. Core workspace")
    workspace, cloned = ensure_workspace_clone(target_dir)
    print(f"   {'Cloned' if cloned else 'Using'} workspace at {workspace}")
    python_path = ensure_virtualenv(workspace)
    print(f"   Virtualenv Python: {python_path}")
    print("")

    print("4. Environment bootstrap")
    env_path, env_copied = copy_example_env(workspace, force=args.force_env)
    if env_copied:
        print(f"   Wrote {env_path} from example.env")
    else:
        print(f"   Keeping existing environment file at {env_path}")
    write_notification_env_defaults(workspace)
    print(f"   Added notification defaults to {env_path}")
    if not args.skip_notification_setup:
        configure_notification_env_interactively(workspace, assume_yes=args.yes)
        print("   Telegram and Apple Messages onboarding defaults are ready in .env")
    print("")

    active_config_path = workspace / "shared" / "configs" / "config.yaml"
    if not args.skip_config_copy:
        print("5. Config bootstrap")
        copied_path, copied = copy_example_config(workspace, force=args.force_config_copy)
        if copied:
            print(f"   Copied example config to {copied_path}")
        else:
            print(f"   Keeping existing config at {copied_path}")
        active_config_path = copied_path
        print("")

    if not args.skip_python_requirements:
        print("6. Python requirements")
        print("   Installing service requirements from webapp, ingestor, reid, anomaly, and association")
        if _prompt_yes_no("   Install Python requirements now?", default=True, assume_yes=args.yes):
            install_python_requirements(workspace, python_executable=str(python_path))
            print("   Python requirements installed.")
        print("")

    if not args.skip_cuda_detection:
        print("7. Runtime profile defaults")
        recommendation = detect_runtime_profile_recommendation()
        print(f"   Recommendation: {recommendation.profile.upper()}")
        print(f"   Reason: {recommendation.reason}")
        if active_config_path.exists():
            apply_runtime_profile_defaults(active_config_path, recommendation)
            print(f"   Updated config devices in {active_config_path}")
        env_path = write_runtime_profile_env_defaults(workspace, recommendation)
        print(f"   Wrote CLI defaults to {env_path}")
        print("")

    if not args.skip_infra_init:
        print("8. Docker infrastructure")
        infra = start_docker_infra(workspace, start_webapp=args.start_webapp)
        print(f"   Started services: {', '.join(infra.services)}")
        print("")

        print("9. Database initialization")
        run_workspace_reset_db(workspace, python_path)
        print("   reset-db completed successfully")
        seeded_subscriptions = sync_notification_subscriptions_from_env(workspace)
        if seeded_subscriptions:
            print("   Seeded notification subscriptions: " + ", ".join(seeded_subscriptions))
        else:
            print("   No Telegram or Apple Messages subscriptions were seeded from .env")
        print("")

    save_default_workspace(workspace)
    print(f"Saved default workspace: {workspace}")
    print("Next step")
    print(f"  hearthlight start --workspace {workspace} --profile {detect_runtime_profile_recommendation().profile}")

    return 0
