from __future__ import annotations

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
from shared.utils.image_variants import (
    IMAGE_VARIANTS,
    default_image_services_for_variant,
    normalize_selected_services,
    resolve_image_variant,
)
from shared.utils.local_worker_runtime import (
    WORKER_RUNTIME_DOCKER,
    WORKER_RUNTIME_HYBRID_LOCAL_CPU,
    WORKER_RUNTIME_HYBRID_LOCAL_MLX,
    detect_default_worker_runtime,
)
try:
    from shared.utils.model_registry import build_model_display_name, load_registry_bundle
except ModuleNotFoundError:  # pragma: no cover - launcher fallback in thin test envs
    build_model_display_name = None
    load_registry_bundle = None
from hearthlight.runtime import run_local_reset_db
from hearthlight.runtime import load_project_env_file, resolve_start_defaults

try:
    from hearthlight_model_zoo.catalog import load_master_catalog
except ModuleNotFoundError:  # pragma: no cover - optional during bootstrap
    load_master_catalog = None

CONFIG_DIR = ROOT_DIR / "shared" / "configs"
ACTIVE_CONFIG_PATH = CONFIG_DIR / "config.yaml"
GENERATED_CONFIG_DIR = CONFIG_DIR / "generated"
REGISTRY_DIR = ROOT_DIR / "shared" / "configs" / "registries"
BASE_COMPOSE_PATH = ROOT_DIR / "docker-compose.yaml"
CUDA_COMPOSE_PATH = ROOT_DIR / "run" / "docker-compose.cuda.yaml"
CORE_SERVICES = ["db", "rabbitmq", "webapp", "reverse_proxy"]
FULL_STACK_SERVICES = CORE_SERVICES + ["ingestor", "association", "anomaly"]
REGISTRY_STAGE_LABELS = {
    "detector": "Detector",
    "tracker": "Tracker",
    "anomaly_stage_1": "Heuristic Filter",
    "anomaly_stage_2": "Anomaly Stage 2",
}
PUBLISHED_IMAGE_ENV_BY_SERVICE = {
    "rabbitmq": "HEARTHLIGHT_RABBITMQ_IMAGE",
    "webapp": "HEARTHLIGHT_WEBAPP_IMAGE",
    "ingestor": "HEARTHLIGHT_INGESTOR_IMAGE",
    "association": "HEARTHLIGHT_ASSOCIATION_IMAGE",
    "anomaly": "HEARTHLIGHT_ANOMALY_IMAGE",
}


@dataclass(frozen=True)
class LaunchSelection:
    template_path: Path
    source_preset_path: Path | None
    worker_runtime: str
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

def detect_worker_runtime(profile: str) -> tuple[str, str]:
    runtime = detect_default_worker_runtime(profile=profile)
    if runtime == WORKER_RUNTIME_HYBRID_LOCAL_MLX:
        return runtime, "defaulting to hybrid-local-mlx on Apple Silicon CPU runs"
    if runtime == WORKER_RUNTIME_HYBRID_LOCAL_CPU:
        return runtime, "defaulting to hybrid-local-cpu on macOS CPU full-stack runs"
    return runtime, "defaulting to docker worker runtime"


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


def _normalize_yaml_scalar(value: str) -> str:
    return value.strip().strip("'").strip('"')


def _parse_registry_file(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []

    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    section: str | None = None
    for raw_line in path.read_text().splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        top_level = re.match(r"^([A-Za-z0-9_.-]+):\s*$", raw_line)
        if top_level:
            current = {"model_key": top_level.group(1), "runtime": {}}
            entries.append(current)
            section = None
            continue
        if current is None:
            continue
        nested = re.match(r"^\s{2}([A-Za-z0-9_.-]+):\s*(.*?)\s*$", raw_line)
        if nested:
            key, value = nested.groups()
            if key == "runtime":
                section = "runtime"
            elif value:
                current[key] = _normalize_yaml_scalar(value)
                section = None
            continue
        runtime_match = re.match(r"^\s{4}([A-Za-z0-9_.-]+):\s*(.*?)\s*$", raw_line)
        if runtime_match and section == "runtime":
            key, value = runtime_match.groups()
            runtime = current.setdefault("runtime", {})
            assert isinstance(runtime, dict)
            runtime[key] = _normalize_yaml_scalar(value)
    return entries

def _load_master_stage_options() -> dict[str, list[str]]:
    if load_master_catalog is None:
        return {}
    try:
        catalog = load_master_catalog()
    except Exception:
        return {}
    stage_options = catalog.get("stage_options") if isinstance(catalog, dict) else {}
    if not isinstance(stage_options, dict):
        return {}
    return {
        str(stage): [str(option) for option in list(options)]
        for stage, options in stage_options.items()
        if isinstance(options, list)
    }


def _registry_option_inventory() -> dict[str, set[str]]:
    options: dict[str, set[str]] = {
        "detector": set(),
        "tracker": set(),
        "reid": set(),
        "anomaly_stage_1": set(),
        "anomaly_stage_2": set(),
        "pose": set(),
        "feature_extractor": set(),
    }
    if load_registry_bundle is not None:
        bundle = load_registry_bundle()
        detector_models = bundle.get("models", {}).get("detector", {})
        for registration in detector_models.values():
            artifact_ref = str((registration or {}).get("artifact_ref") or "").strip()
            if artifact_ref:
                options["detector"].add(artifact_ref)
        tracker_models = bundle.get("models", {}).get("tracker", {})
        for registration in tracker_models.values():
            runtime = (registration or {}).get("runtime") or {}
            tracker_name = str(runtime.get("tracker_name") or "").strip() if isinstance(runtime, dict) else ""
            if tracker_name:
                options["tracker"].add(tracker_name)
                continue
            artifact_ref = str((registration or {}).get("artifact_ref") or "").strip()
            if artifact_ref:
                options["tracker"].add(artifact_ref)
        reid_models = bundle.get("models", {}).get("reid", {})
        for model_key, registration in reid_models.items():
            options["reid"].add(str(model_key))
            runtime = (registration or {}).get("runtime") or {}
            feature_model_name = (
                str(runtime.get("feature_extractor_model") or "").strip()
                if isinstance(runtime, dict)
                else ""
            )
            if feature_model_name:
                options["feature_extractor"].add(feature_model_name)
        for model_key in (bundle.get("models", {}).get("anomaly_stage_1", {}) or {}).keys():
            options["anomaly_stage_1"].add(str(model_key))
        for model_key in (bundle.get("models", {}).get("anomaly_stage_2", {}) or {}).keys():
            options["anomaly_stage_2"].add(str(model_key))
    else:
        for entry in _parse_registry_file(REGISTRY_DIR / "detectors.yaml"):
            artifact_ref = str(entry.get("artifact_ref") or "").strip()
            if artifact_ref:
                options["detector"].add(artifact_ref)
        for entry in _parse_registry_file(REGISTRY_DIR / "trackers.yaml"):
            runtime = entry.get("runtime") or {}
            if isinstance(runtime, dict):
                tracker_name = str(runtime.get("tracker_name") or "").strip()
                if tracker_name:
                    options["tracker"].add(tracker_name)
                    continue
            artifact_ref = str(entry.get("artifact_ref") or "").strip()
            if artifact_ref:
                options["tracker"].add(artifact_ref)
        for entry in _parse_registry_file(REGISTRY_DIR / "reid_models.yaml"):
            model_key = str(entry.get("model_key") or "").strip()
            if model_key:
                options["reid"].add(model_key)
            runtime = entry.get("runtime") or {}
            if isinstance(runtime, dict):
                feature_model_name = str(runtime.get("feature_extractor_model") or "").strip()
                if feature_model_name:
                    options["feature_extractor"].add(feature_model_name)
        for entry in _parse_registry_file(REGISTRY_DIR / "anomaly_stage_1_models.yaml"):
            model_key = str(entry.get("model_key") or "").strip()
            if model_key:
                options["anomaly_stage_1"].add(model_key)
        for entry in _parse_registry_file(REGISTRY_DIR / "anomaly_stage_2_models.yaml"):
            model_key = str(entry.get("model_key") or "").strip()
            if model_key:
                options["anomaly_stage_2"].add(model_key)
    for key, values in _load_master_stage_options().items():
        if key in options:
            options[key].update(values)
    return options


def _registry_stage_display_inventory() -> dict[str, list[str]]:
    if load_registry_bundle is None or build_model_display_name is None:
        return {}
    bundle = load_registry_bundle()
    inventory: dict[str, list[str]] = {}
    for stage in ("detector", "tracker", "reid", "anomaly_stage_1", "anomaly_stage_2"):
        stage_models = bundle.get("models", {}).get(stage, {}) or {}
        display_rows: list[str] = []
        for model_key, registration in sorted(stage_models.items()):
            display_name = build_model_display_name(stage, str(model_key), registration or {})
            display_rows.append(f"{display_name} [{model_key}]")
        inventory[stage] = display_rows
    return inventory


def extract_registry_model_names() -> list[str]:
    names = set()
    inventory = _registry_option_inventory()
    for values in inventory.values():
        names.update(values)
    return sorted(names)


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
        "reid": set(),
        "anomaly_stage_1": set(),
        "anomaly_stage_2": set(),
        "pose": set(),
        "feature_extractor": set(),
    }

    for path in list_config_templates().values():
        for key, values in _scan_section_values(path.read_text()).items():
            combined[key].update(values)

    for key, values in _registry_option_inventory().items():
        combined[key].update(values)

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

    def _has_nested_children(start_index: int) -> bool:
        for nested_index in range(start_index + 1, section_end):
            nested_raw = lines[nested_index]
            nested_stripped = nested_raw.strip()
            if not nested_stripped:
                continue
            nested_indent = len(nested_raw) - len(nested_raw.lstrip(" "))
            return nested_indent > parent_indent + 2
        return False

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
            insert_index = index if _has_nested_children(index) else index + 1

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
    config_text = set_nested_scalar(
        config_text, ["anomaly"], "device", "cuda:0" if selection.use_cuda else "cpu"
    )
    effective_show_video = (
        False
        if selection.worker_runtime in {WORKER_RUNTIME_HYBRID_LOCAL_CPU, WORKER_RUNTIME_HYBRID_LOCAL_MLX}
        else selection.show_video
    )
    config_text = set_nested_scalar(config_text, ["output", "visualize"], "show_vid", effective_show_video)

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
        f"# worker_runtime: {selection.worker_runtime}",
        f"# show_video: {effective_show_video}",
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
    env["HEARTHLIGHT_WORKER_RUNTIME"] = selection.worker_runtime
    env["HEARTHLIGHT_HOST_PROJECT_ROOT"] = str(ROOT_DIR)
    env["HEARTHLIGHT_IMAGE_VARIANT"] = resolve_image_variant(
        use_cuda=selection.use_cuda,
        worker_runtime=selection.worker_runtime,
    )
    return env


def configured_published_services(services: Iterable[str]) -> list[str]:
    env_file_values = load_project_env_file(ROOT_DIR)
    configured: list[str] = []
    for service in services:
        image_var = PUBLISHED_IMAGE_ENV_BY_SERVICE.get(service)
        if image_var and str(env_file_values.get(image_var, "")).strip():
            configured.append(service)
    return configured


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


def prepare_local_images(
    *,
    profile: str,
    worker_runtime: str,
    services: Iterable[str] | None = None,
    variant_override: str | None = None,
    dry_run: bool = False,
    write_env: str | None = None,
) -> int:
    docker_binary = find_docker_binary()
    if docker_binary is None:
        raise SystemExit("Docker CLI not found. Install Docker Desktop or add docker to PATH.")
    use_cuda = profile == "cuda"
    variant = variant_override or resolve_image_variant(use_cuda=use_cuda, worker_runtime=worker_runtime)
    selected_services = normalize_selected_services(services, variant=variant)
    env = build_docker_env(docker_binary)
    env.setdefault("RELOAD", "")
    env["HEARTHLIGHT_WORKER_RUNTIME"] = worker_runtime
    env["HEARTHLIGHT_HOST_PROJECT_ROOT"] = str(ROOT_DIR)
    env["HEARTHLIGHT_IMAGE_VARIANT"] = variant
    command = compose_command(docker_binary, use_cuda) + ["build", *selected_services]

    print(f"Detected profile: {profile}")
    print(f"Worker runtime: {worker_runtime}")
    print(f"Image variant: {variant}")
    print(f"Services: {', '.join(selected_services)}")
    print(f"Compose files: {', '.join(str(path) for path in compose_files(use_cuda))}")

    if dry_run:
        print("DRY RUN:", " ".join(command))
        if write_env:
            print(f"DRY RUN: would update {write_env} with HEARTHLIGHT_IMAGE_VARIANT={variant}")
        return 0

    subprocess.run(command, cwd=ROOT_DIR, env=env, check=True)

    if write_env:
        env_path = (ROOT_DIR / write_env).resolve() if not Path(write_env).is_absolute() else Path(write_env)
        update_env_file(env_path, {"HEARTHLIGHT_IMAGE_VARIANT": variant})
        print(f"Wrote image variant to {env_path}")

    print("Docker image preparation completed")
    return 0


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
    docker_full_stack = selection.worker_runtime == WORKER_RUNTIME_DOCKER
    services = FULL_STACK_SERVICES if docker_full_stack else CORE_SERVICES
    published_services = configured_published_services(services)
    image_variant = env["HEARTHLIGHT_IMAGE_VARIANT"]

    print(f"Template: {selection.template_path}")
    print(
        "Source preset: "
        + (str(selection.source_preset_path) if selection.source_preset_path is not None else "template default")
    )
    print("Service startup: full system")
    print(f"Worker runtime: {selection.worker_runtime}")
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
    print(f"Image variant: {image_variant}")
    if selection.use_cuda:
        print(f"CUDA_VISIBLE_DEVICES={selection.cuda_visible_devices or 'all'}")
    elif selection.worker_runtime == WORKER_RUNTIME_HYBRID_LOCAL_MLX:
        print("Running in CPU mode with host MLX-backed local workers")
    else:
        print("Running in CPU mode")
    if published_services:
        print(f"Published images: {', '.join(published_services)}")
    else:
        print(f"Prepared local image services: {', '.join(default_image_services_for_variant(image_variant))}")

    if dry_run:
        return 0

    if published_services:
        subprocess.run(command + ["pull", *published_services], cwd=ROOT_DIR, env=env, check=True)

    subprocess.run(command + ["up", "-d", "db", "rabbitmq"], cwd=ROOT_DIR, env=env, check=True)

    if not selection.skip_reset_db:
        run_local_reset_db(ROOT_DIR)

    if selection.open_dashboard:
        dashboard_thread = threading.Thread(target=_wait_and_open_dashboard, daemon=True)
        dashboard_thread.start()

    if selection.worker_runtime in {WORKER_RUNTIME_HYBRID_LOCAL_CPU, WORKER_RUNTIME_HYBRID_LOCAL_MLX}:
        subprocess.run(command + ["up", "-d", *CORE_SERVICES], cwd=ROOT_DIR, env=env, check=True)
        return subprocess.call(
            [sys.executable, "-m", "hearthlight.local_workers", "start"],
            cwd=ROOT_DIR,
            env=env,
        )

    return subprocess.call(command + ["up", *services], cwd=ROOT_DIR, env=env)


def _wait_and_open_dashboard():
    if wait_for_dashboard():
        webbrowser.open("http://localhost:3000")


def stop_stack(use_cuda: bool = False) -> int:
    subprocess.call(
        [sys.executable, "-m", "hearthlight.local_workers", "stop"],
        cwd=ROOT_DIR,
        env=os.environ.copy(),
    )
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
    start_defaults = resolve_start_defaults(ROOT_DIR)

    template_name = prompt_choice("Config template", list(templates.keys()), default="active" if "active" in templates else next(iter(templates)))
    source_preset_name = prompt_choice(
        "Camera/source preset",
        ["template default", *templates.keys()],
        default=template_name,
    )
    profile = prompt_choice(
        "Execution profile",
        ["cpu", "cuda"],
        default="cuda" if "cuda" in current.get("rtdetr_device", "") else start_defaults["profile"],
    )
    detected_worker_runtime, detected_worker_runtime_reason = detect_worker_runtime(profile)
    worker_runtime = prompt_choice(
        f"Worker runtime ({detected_worker_runtime_reason})",
        [WORKER_RUNTIME_DOCKER, WORKER_RUNTIME_HYBRID_LOCAL_CPU, WORKER_RUNTIME_HYBRID_LOCAL_MLX],
        default=detected_worker_runtime,
    )
    use_cuda = profile == "cuda"
    detector_device = start_defaults["detector_device"] if use_cuda else "cpu"
    pose_device = start_defaults["pose_device"] if use_cuda else "cpu"
    feature_device = start_defaults["feature_device"] if use_cuda else "cpu"
    default_cuda_visible_devices = start_defaults["cuda_visible_devices"] or "all"
    cuda_visible_devices = input(f"CUDA visible devices [{default_cuda_visible_devices}]: ").strip() if use_cuda else ""
    if use_cuda and not cuda_visible_devices:
        cuda_visible_devices = default_cuda_visible_devices

    pose_enabled = prompt_bool("Enable pose estimation", default=current.get("pose_enable", "false").lower() == "true")
    show_video = prompt_bool("Show video windows", default=current.get("show_vid", "true").lower() == "true")
    reload = prompt_bool("Enable reload mode", default=False)
    reset_database = prompt_bool("Reset database before startup", default=False)
    open_dashboard = prompt_bool("Open dashboard automatically", default=True)

    return LaunchSelection(
        template_path=templates[template_name],
        source_preset_path=None if source_preset_name == "template default" else templates[source_preset_name],
        worker_runtime=worker_runtime,
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
        skip_reset_db=not reset_database,
        open_dashboard=open_dashboard,
    )


def print_model_inventory() -> None:
    templates = list_config_templates()
    model_options = discover_model_options()
    registry_inventory = _registry_stage_display_inventory()
    print("Config templates:")
    for name, path in templates.items():
        print(f"  - {name}: {path}")
    print("\nDiscovered model options:")
    for key, values in model_options.items():
        print(f"  - {key}: {', '.join(values) if values else 'none'}")
    if registry_inventory:
        print("\nRegistry-backed stage inventory:")
        for stage, values in registry_inventory.items():
            label = REGISTRY_STAGE_LABELS.get(stage, stage)
            print(f"  - {label}: {', '.join(values) if values else 'none'}")
    print("\nRegistry-only entries:")
    for value in extract_registry_model_names():
        print(f"  - {value}")


def build_selection_from_args(args) -> LaunchSelection:
    templates = list_config_templates()
    model_options = discover_model_options()
    current = read_current_selection()
    start_defaults = resolve_start_defaults(ROOT_DIR)

    template_key = args.template or ("active" if "active" in templates else next(iter(templates)))
    if template_key not in templates:
        raise SystemExit(f"Unknown config template '{template_key}'. Use 'list-models' to inspect choices.")
    if args.source_preset and args.source_preset not in templates:
        raise SystemExit(
            f"Unknown source preset '{args.source_preset}'. Use 'list-models' to inspect choices."
        )

    use_cuda = args.profile == "cuda"
    detected_worker_runtime, _ = detect_worker_runtime(args.profile)
    detector_device = args.detector_device or (
        start_defaults["detector_device"] if use_cuda else "cpu"
    )
    pose_device = args.pose_device or (start_defaults["pose_device"] if use_cuda else "cpu")
    feature_device = args.feature_device or (
        start_defaults["feature_device"] if use_cuda else "cpu"
    )
    pose_enabled = args.pose_enabled if args.pose_enabled is not None else current.get("pose_enable", "false").lower() == "true"

    return LaunchSelection(
        template_path=templates[template_key],
        source_preset_path=templates[args.source_preset] if args.source_preset else None,
        worker_runtime=args.worker_runtime or detected_worker_runtime,
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
        cuda_visible_devices=args.cuda_visible_devices or (
            start_defaults["cuda_visible_devices"] if use_cuda else ""
        ),
        reload=args.reload,
        skip_reset_db=args.skip_reset_db,
        open_dashboard=args.open_dashboard,
    )
