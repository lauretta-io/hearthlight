from __future__ import annotations

import ast
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.utils.docker_cli import build_docker_env, find_docker_binary
from hearthlight.runtime import run_local_reset_db

CONFIG_DIR = ROOT_DIR / "shared" / "configs"
ACTIVE_CONFIG_PATH = CONFIG_DIR / "config.yaml"
GENERATED_CONFIG_DIR = CONFIG_DIR / "generated"
DOWNLOAD_WEIGHTS_PATH = ROOT_DIR / "shared" / "utils" / "download_weights.py"
BASE_COMPOSE_PATH = ROOT_DIR / "docker-compose.yaml"
CUDA_COMPOSE_PATH = ROOT_DIR / "run" / "docker-compose.cuda.yaml"
API_SERVICES = ["db", "rabbitmq", "webapp"]
PIPELINE_SERVICES = API_SERVICES + ["ingestor", "reid", "association", "anomaly"]


@dataclass(frozen=True)
class LaunchSelection:
    template_path: Path
    source_preset_path: Path | None
    run_mode: str
    detector_model: str
    tracker_model: str
    detector_device: str
    pose_enabled: bool
    pose_model: str
    pose_device: str
    feature_extractor_model: str
    feature_extractor_device: str
    show_video: bool
    use_cuda: bool
    cuda_visible_devices: str
    reload: bool
    skip_reset_db: bool
    open_dashboard: bool


def detect_run_mode() -> tuple[str, str]:
    explicit_mode = os.environ.get("HEARTHLIGHT_DOCKER_MODE", "").strip().lower()
    if explicit_mode in {"api", "pipeline"}:
        return explicit_mode, f"using HEARTHLIGHT_DOCKER_MODE={explicit_mode}"

    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin" or machine in {"arm64", "aarch64"}:
        return "api", f"defaulting to API mode on {system} {machine}"
    return "pipeline", f"defaulting to full pipeline mode on {system} {machine}"


def list_config_templates() -> dict[str, Path]:
    templates: dict[str, Path] = {}
    if ACTIVE_CONFIG_PATH.exists():
        templates["active"] = ACTIVE_CONFIG_PATH
    example_path = CONFIG_DIR / "example_config.yaml"
    if example_path.exists():
        templates["example"] = example_path
    saved_dir = CONFIG_DIR / "saved_configs"
    if saved_dir.exists():
        for path in sorted(saved_dir.glob("*.yaml")):
            templates[path.stem] = path
    return templates


def extract_registry_model_names(download_weights_path: Path = DOWNLOAD_WEIGHTS_PATH) -> list[str]:
    if not download_weights_path.exists():
        return []

    module = ast.parse(download_weights_path.read_text())
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "MODEL_REGISTRY":
                    registry = ast.literal_eval(node.value)
                    return sorted(str(key) for key in registry.keys())
    return []


def _scan_section_values(text: str) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {
        "detector": set(),
        "tracker": set(),
        "pose": set(),
        "feature_extractor": set(),
    }
    current_section: str | None = None
    for line in text.splitlines():
        section_match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*$", line)
        if section_match:
            current_section = section_match.group(1)
            continue

        scalar_match = re.match(
            r"^\s{2}([A-Za-z_][A-Za-z0-9_]*):\s*([^#\n]+?)\s*(?:#.*)?$",
            line,
        )
        if not scalar_match or current_section is None:
            continue

        key = scalar_match.group(1)
        value = scalar_match.group(2).strip()
        if current_section == "rtdetr" and key == "model_name":
            values["detector"].add(value)
        elif current_section == "tracking" and key in {"tracker", "track_method"}:
            values["tracker"].add(value)
        elif current_section == "pose" and key == "model_name":
            values["pose"].add(value)
        elif current_section == "feature_extractor" and key == "model_name":
            values["feature_extractor"].add(value)
    return values


def discover_model_options() -> dict[str, list[str]]:
    combined: dict[str, set[str]] = {
        "detector": set(),
        "tracker": set(),
        "pose": set(),
        "feature_extractor": set(),
    }

    for path in list_config_templates().values():
        for key, values in _scan_section_values(path.read_text()).items():
            combined[key].update(values)

    for model_name in extract_registry_model_names():
        if model_name.startswith(("dfine", "rtdetr")):
            combined["detector"].add(model_name)
        elif model_name.startswith("rtmo"):
            combined["pose"].add(model_name)
        elif "transformer" in model_name or "vit" in model_name:
            combined["feature_extractor"].add(model_name)

    return {key: sorted(values) for key, values in combined.items()}


def read_current_selection(config_path: Path = ACTIVE_CONFIG_PATH) -> dict[str, str]:
    if not config_path.exists():
        return {}
    text = config_path.read_text()
    current = _scan_section_values(text)
    values: dict[str, str] = {}
    for key, choices in current.items():
        if choices:
            values[key] = sorted(choices)[0]
    for section, config_key in [
        ("rtdetr", "device"),
        ("pose", "device"),
        ("feature_extractor", "device"),
    ]:
        value = get_nested_scalar(text, [section], config_key)
        if value is not None:
            values[f"{section}_device"] = value
    show_vid = get_nested_scalar(text, ["output", "visualize"], "show_vid")
    if show_vid is not None:
        values["show_vid"] = show_vid
    pose_enable = get_nested_scalar(text, ["pose"], "enable")
    if pose_enable is not None:
        values["pose_enable"] = pose_enable
    return values


def _render_yaml_scalar(value: str | bool | int | float) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if re.match(r"^[A-Za-z0-9._:/+-]+$", value):
        return value
    return json.dumps(value)


def _find_section_bounds(lines: list[str], path: list[str]) -> tuple[int, int, int] | None:
    search_start = 0
    search_end = len(lines)
    parent_indent = -2

    for section in path:
        found_index = None
        target_indent = parent_indent + 2
        pattern = re.compile(rf"^\s{{{target_indent}}}{re.escape(section)}:\s*(?:#.*)?$")
        for index in range(search_start, search_end):
            if pattern.match(lines[index]):
                found_index = index
                break
        if found_index is None:
            return None

        block_end = len(lines)
        for index in range(found_index + 1, search_end):
            raw = lines[index]
            stripped = raw.strip()
            if not stripped:
                continue
            indent = len(raw) - len(raw.lstrip(" "))
            if indent <= target_indent:
                block_end = index
                break

        search_start = found_index + 1
        search_end = block_end
        parent_indent = target_indent

    return found_index, parent_indent, search_end


def get_top_level_block(text: str, key: str) -> str | None:
    lines = text.splitlines()
    section_info = _find_section_bounds(lines, [key])
    if section_info is None:
        return None
    start_index, _, end_index = section_info
    return "\n".join(lines[start_index:end_index]) + "\n"


def set_top_level_block(text: str, key: str, block_text: str) -> str:
    lines = text.splitlines()
    section_info = _find_section_bounds(lines, [key])
    block_lines = block_text.rstrip("\n").splitlines()

    if section_info is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(block_lines)
        return "\n".join(lines) + "\n"

    start_index, _, end_index = section_info
    updated_lines = lines[:start_index] + block_lines + lines[end_index:]
    return "\n".join(updated_lines) + "\n"


def get_nested_scalar(text: str, path: list[str], key: str) -> str | None:
    lines = text.splitlines()
    section_info = _find_section_bounds(lines, path)
    if section_info is None:
        return None

    _, parent_indent, section_end = section_info
    key_pattern = re.compile(
        rf"^\s{{{parent_indent + 2}}}{re.escape(key)}:\s*([^#\n]+?)\s*(?:#.*)?$"
    )
    section_start = section_info[0] + 1
    for index in range(section_start, section_end):
        match = key_pattern.match(lines[index])
        if match:
            return match.group(1).strip()
    return None


def set_nested_scalar(text: str, path: list[str], key: str, value: str | bool | int | float) -> str:
    lines = text.splitlines()
    section_info = _find_section_bounds(lines, path)

    if section_info is None:
        if lines and lines[-1].strip():
            lines.append("")
        indent = 0
        for section in path:
            lines.append(" " * indent + f"{section}:")
            indent += 2
        lines.append(" " * indent + f"{key}: {_render_yaml_scalar(value)}")
        return "\n".join(lines) + "\n"

    section_index, parent_indent, section_end = section_info
    key_pattern = re.compile(rf"^\s{{{parent_indent + 2}}}{re.escape(key)}:\s*")
    replacement = " " * (parent_indent + 2) + f"{key}: {_render_yaml_scalar(value)}"
    insert_index = section_end

    for index in range(section_index + 1, section_end):
        raw = lines[index]
        stripped = raw.strip()
        if not stripped:
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent == parent_indent + 2 and key_pattern.match(raw):
            lines[index] = replacement
            return "\n".join(lines) + "\n"
        if indent == parent_indent + 2:
            insert_index = index + 1

    lines.insert(insert_index, replacement)
    return "\n".join(lines) + "\n"


def build_effective_config(selection: LaunchSelection, activate: bool = True) -> tuple[Path, Path]:
    GENERATED_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    template_text = selection.template_path.read_text()

    config_text = template_text
    if selection.source_preset_path is not None:
        source_text = selection.source_preset_path.read_text()
        for block_name in ("input", "passenger_zones", "tray_zones"):
            block_text = get_top_level_block(source_text, block_name)
            if block_text is not None:
                config_text = set_top_level_block(config_text, block_name, block_text)
    config_text = set_nested_scalar(config_text, ["tracking"], "tracker", selection.tracker_model)
    config_text = set_nested_scalar(config_text, ["tracking"], "track_method", selection.tracker_model)
    config_text = set_nested_scalar(config_text, ["rtdetr"], "model_name", selection.detector_model)
    config_text = set_nested_scalar(config_text, ["rtdetr"], "device", selection.detector_device)
    config_text = set_nested_scalar(config_text, ["pose"], "enable", selection.pose_enabled)
    config_text = set_nested_scalar(config_text, ["pose"], "model_name", selection.pose_model)
    config_text = set_nested_scalar(config_text, ["pose"], "device", selection.pose_device)
    config_text = set_nested_scalar(
        config_text, ["feature_extractor"], "model_name", selection.feature_extractor_model
    )
    config_text = set_nested_scalar(
        config_text, ["feature_extractor"], "device", selection.feature_extractor_device
    )
    config_text = set_nested_scalar(config_text, ["output", "visualize"], "show_vid", selection.show_video)

    generated_name = (
        f"launcher_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{selection.template_path.stem}.yaml"
    )
    generated_path = GENERATED_CONFIG_DIR / generated_name
    header = [
        "# Generated by hearthlight",
        f"# template: {selection.template_path}",
        f"# source_preset: {selection.source_preset_path or 'template default'}",
        f"# detector: {selection.detector_model}",
        f"# tracker: {selection.tracker_model}",
        f"# pose_enabled: {selection.pose_enabled}",
        f"# pose_model: {selection.pose_model}",
        f"# feature_extractor: {selection.feature_extractor_model}",
        f"# use_cuda: {selection.use_cuda}",
        "",
    ]
    generated_path.write_text("\n".join(header) + config_text)
    if activate:
        shutil.copyfile(generated_path, ACTIVE_CONFIG_PATH)
    return generated_path, ACTIVE_CONFIG_PATH


def compose_files(use_cuda: bool) -> list[Path]:
    files = [BASE_COMPOSE_PATH]
    if use_cuda:
        files.append(CUDA_COMPOSE_PATH)
    return files


def compose_command(docker_binary: str, use_cuda: bool) -> list[str]:
    command = [docker_binary, "compose"]
    for path in compose_files(use_cuda):
        command.extend(["-f", str(path)])
    return command


def compose_environment(selection: LaunchSelection) -> dict[str, str]:
    docker_binary = find_docker_binary()
    env = build_docker_env(docker_binary)
    env["RELOAD"] = "1" if selection.reload else ""
    env["CUDA_VISIBLE_DEVICES"] = selection.cuda_visible_devices if selection.use_cuda else ""
    return env


def wait_for_dashboard(timeout_seconds: float = 30.0) -> bool:
    import urllib.request

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://localhost:3000", timeout=1) as response:
                if 200 <= response.status < 500:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def start_stack(selection: LaunchSelection, dry_run: bool = False) -> int:
    generated_path, active_path = build_effective_config(selection, activate=not dry_run)
    docker_binary = find_docker_binary()
    if docker_binary is None:
        raise SystemExit("Docker CLI not found. Install Docker Desktop or add docker to PATH.")
    command = compose_command(docker_binary, selection.use_cuda)
    env = compose_environment(selection)
    services = PIPELINE_SERVICES if selection.run_mode == "pipeline" else API_SERVICES

    print(f"Template: {selection.template_path}")
    print(
        "Source preset: "
        + (str(selection.source_preset_path) if selection.source_preset_path is not None else "template default")
    )
    print(f"Run mode: {selection.run_mode}")
    print(f"Generated config: {generated_path}")
    print(f"Active config: {active_path}")
    print(f"Detector: {selection.detector_model} on {selection.detector_device}")
    print(f"Tracker: {selection.tracker_model}")
    print(
        f"Pose: {'enabled' if selection.pose_enabled else 'disabled'}"
        + (f" ({selection.pose_model} on {selection.pose_device})" if selection.pose_enabled else "")
    )
    print(
        f"Feature extractor: {selection.feature_extractor_model} on {selection.feature_extractor_device}"
    )
    print(f"Compose files: {', '.join(str(path) for path in compose_files(selection.use_cuda))}")
    print(f"Services: {', '.join(services)}")
    if selection.use_cuda:
        print(f"CUDA_VISIBLE_DEVICES={selection.cuda_visible_devices or 'all'}")
    else:
        print("Running in CPU mode")

    if dry_run:
        return 0

    subprocess.run(command + ["up", "-d", "db", "rabbitmq"], cwd=ROOT_DIR, env=env, check=True)

    if not selection.skip_reset_db:
        run_local_reset_db(ROOT_DIR)

    if selection.open_dashboard:
        dashboard_thread = threading.Thread(target=_wait_and_open_dashboard, daemon=True)
        dashboard_thread.start()

    return subprocess.call(command + ["up", *services], cwd=ROOT_DIR, env=env)


def _wait_and_open_dashboard():
    if wait_for_dashboard():
        webbrowser.open("http://localhost:3000")


def stop_stack(use_cuda: bool = False) -> int:
    docker_binary = find_docker_binary()
    if docker_binary is None:
        raise SystemExit("Docker CLI not found. Install Docker Desktop or add docker to PATH.")
    return subprocess.call(
        compose_command(docker_binary, use_cuda) + ["down", "--remove-orphans"],
        cwd=ROOT_DIR,
        env=build_docker_env(docker_binary),
    )


def prompt_choice(label: str, options: list[str], default: str | None = None) -> str:
    if not options:
        raise ValueError(f"No options available for {label}")

    print(f"\n{label}:")
    for index, option in enumerate(options, start=1):
        suffix = " (default)" if option == default else ""
        print(f"  {index}. {option}{suffix}")

    while True:
        raw = input("Select option number (Enter for default): ").strip()
        if not raw and default is not None:
            return default
        try:
            selected = options[int(raw) - 1]
            return selected
        except (ValueError, IndexError):
            print("Invalid selection. Try again.")


def prompt_bool(label: str, default: bool) -> bool:
    prompt = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{label} [{prompt}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Please answer yes or no.")


def build_interactive_selection() -> LaunchSelection:
    templates = list_config_templates()
    model_options = discover_model_options()
    current = read_current_selection()

    template_name = prompt_choice("Config template", list(templates.keys()), default="active" if "active" in templates else next(iter(templates)))
    source_preset_name = prompt_choice(
        "Camera/source preset",
        ["template default", *templates.keys()],
        default=template_name,
    )
    detected_run_mode, detected_run_mode_reason = detect_run_mode()
    run_mode = prompt_choice(
        f"Runtime service mode ({detected_run_mode_reason})",
        ["api", "pipeline"],
        default=detected_run_mode,
    )
    profile = prompt_choice("Execution profile", ["cpu", "cuda"], default="cuda" if "cuda" in current.get("rtdetr_device", "") else "cpu")
    use_cuda = profile == "cuda"
    detector_device = "cuda" if use_cuda else "cpu"
    pose_device = "cuda" if use_cuda else "cpu"
    feature_device = "cuda:0" if use_cuda else "cpu"
    cuda_visible_devices = input("CUDA visible devices [all]: ").strip() if use_cuda else ""
    if use_cuda and not cuda_visible_devices:
        cuda_visible_devices = "all"

    pose_enabled = prompt_bool("Enable pose estimation", default=current.get("pose_enable", "false").lower() == "true")
    show_video = prompt_bool("Show video windows", default=current.get("show_vid", "true").lower() == "true")
    reload = prompt_bool("Enable reload mode", default=False)
    skip_reset_db = prompt_bool("Skip reset-db", default=False)
    open_dashboard = prompt_bool("Open dashboard automatically", default=True)

    return LaunchSelection(
        template_path=templates[template_name],
        source_preset_path=None if source_preset_name == "template default" else templates[source_preset_name],
        run_mode=run_mode,
        detector_model=prompt_choice("Detector model", model_options["detector"], default=current.get("detector")),
        tracker_model=prompt_choice("Tracker", model_options["tracker"], default=current.get("tracker")),
        detector_device=detector_device,
        pose_enabled=pose_enabled,
        pose_model=prompt_choice("Pose model", model_options["pose"], default=current.get("pose")) if pose_enabled else current.get("pose", model_options["pose"][0]),
        pose_device=pose_device,
        feature_extractor_model=prompt_choice(
            "Feature extractor", model_options["feature_extractor"], default=current.get("feature_extractor")
        ),
        feature_extractor_device=feature_device,
        show_video=show_video,
        use_cuda=use_cuda,
        cuda_visible_devices=cuda_visible_devices,
        reload=reload,
        skip_reset_db=skip_reset_db,
        open_dashboard=open_dashboard,
    )


def print_model_inventory() -> None:
    templates = list_config_templates()
    model_options = discover_model_options()
    print("Config templates:")
    for name, path in templates.items():
        print(f"  - {name}: {path}")
    print("\nDiscovered model options:")
    for key, values in model_options.items():
        print(f"  - {key}: {', '.join(values) if values else 'none'}")
    print("\nRegistry-only entries:")
    for value in extract_registry_model_names():
        print(f"  - {value}")


def build_selection_from_args(args) -> LaunchSelection:
    templates = list_config_templates()
    model_options = discover_model_options()
    current = read_current_selection()

    template_key = args.template or ("active" if "active" in templates else next(iter(templates)))
    if template_key not in templates:
        raise SystemExit(f"Unknown config template '{template_key}'. Use 'list-models' to inspect choices.")
    if args.source_preset and args.source_preset not in templates:
        raise SystemExit(
            f"Unknown source preset '{args.source_preset}'. Use 'list-models' to inspect choices."
        )

    use_cuda = args.profile == "cuda"
    detected_run_mode, _ = detect_run_mode()
    detector_device = args.detector_device or ("cuda" if use_cuda else "cpu")
    pose_device = args.pose_device or ("cuda" if use_cuda else "cpu")
    feature_device = args.feature_device or ("cuda:0" if use_cuda else "cpu")
    pose_enabled = args.pose_enabled if args.pose_enabled is not None else current.get("pose_enable", "false").lower() == "true"

    return LaunchSelection(
        template_path=templates[template_key],
        source_preset_path=templates[args.source_preset] if args.source_preset else None,
        run_mode=args.mode or detected_run_mode,
        detector_model=args.detector or current.get("detector") or model_options["detector"][0],
        tracker_model=args.tracker or current.get("tracker") or model_options["tracker"][0],
        detector_device=detector_device,
        pose_enabled=pose_enabled,
        pose_model=args.pose_model or current.get("pose") or model_options["pose"][0],
        pose_device=pose_device,
        feature_extractor_model=(
            args.feature_extractor
            or current.get("feature_extractor")
            or model_options["feature_extractor"][0]
        ),
        feature_extractor_device=feature_device,
        show_video=args.show_video if args.show_video is not None else current.get("show_vid", "true").lower() == "true",
        use_cuda=use_cuda,
        cuda_visible_devices=args.cuda_visible_devices or ("all" if use_cuda else ""),
        reload=args.reload,
        skip_reset_db=args.skip_reset_db,
        open_dashboard=args.open_dashboard,
    )
