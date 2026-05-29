from __future__ import annotations

import json
import os
from importlib import metadata
from importlib.util import find_spec
from pathlib import Path
import importlib
import logging
import platform
import re
from typing import Any

from omegaconf import OmegaConf

from ..constants import Tasks

MODEL_STAGE_DETECTOR = "detector"
MODEL_STAGE_TRACKER = "tracker"
MODEL_STAGE_REID = "reid"
MODEL_STAGE_ANOMALY_STAGE_1 = "anomaly_stage_1"
MODEL_STAGE_ANOMALY_STAGE_2 = "anomaly_stage_2"
MODEL_BINDING_STAGES = (
    MODEL_STAGE_DETECTOR,
    MODEL_STAGE_TRACKER,
    MODEL_STAGE_REID,
    MODEL_STAGE_ANOMALY_STAGE_1,
    MODEL_STAGE_ANOMALY_STAGE_2,
)
OPERATOR_MODEL_STAGES = (
    MODEL_STAGE_DETECTOR,
    MODEL_STAGE_TRACKER,
    MODEL_STAGE_ANOMALY_STAGE_1,
    MODEL_STAGE_ANOMALY_STAGE_2,
)
MODEL_ZOO_PACKAGE_NAME = "hearthlight_model_zoo"
MODEL_ZOO_MASTER_CATALOG_SOURCE = "hearthlight_model_zoo:master_catalog.json"
MODEL_ZOO_REPOSITORY_URL = "https://github.com/lauretta-io/hearthlight_model_zoo.git"
MODEL_ZOO_REQUIREMENT_PATHS = (
    Path("webapp/requirements.txt"),
    Path("ingestor/requirements.txt"),
    Path("reid/requirements.txt"),
)
MODEL_ZOO_COMMIT_PATTERN = re.compile(
    r"git\+https://github\.com/lauretta-io/hearthlight_model_zoo\.git@(?P<commit>[0-9a-f]{7,40})"
)

SHARED_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SHARED_ROOT.parent
CONFIG_ROOT = SHARED_ROOT / "configs"
REGISTRY_DIR = CONFIG_ROOT / "registries"
MODEL_BINDINGS_PATH = CONFIG_ROOT / "model_bindings.yaml"
MOUNTED_MODELS_PATH = CONFIG_ROOT / "mounted_models.yaml"

REGISTRY_FILE_MAP = {
    MODEL_STAGE_DETECTOR: "detectors.yaml",
    MODEL_STAGE_TRACKER: "trackers.yaml",
    MODEL_STAGE_REID: "reid_models.yaml",
    MODEL_STAGE_ANOMALY_STAGE_1: "anomaly_stage_1_models.yaml",
    MODEL_STAGE_ANOMALY_STAGE_2: "anomaly_stage_2_models.yaml",
}

STAGE_FIELD_MAP = {
    MODEL_STAGE_DETECTOR: "detector_model_key",
    MODEL_STAGE_TRACKER: "tracker_model_key",
    MODEL_STAGE_REID: "reid_model_key",
    MODEL_STAGE_ANOMALY_STAGE_1: "anomaly_stage_1_model_key",
    MODEL_STAGE_ANOMALY_STAGE_2: "anomaly_stage_2_model_key",
}

LEGACY_TRACKER_NAME_MAP = {
    "builtin_cmtrack": "cmtrack",
    "builtin_ocsort": "ocsort",
    "builtin_botsort": "botsort",
    "builtin_strongsort": "strongsort",
    "builtin_bytetrack": "bytetrack",
    "builtin_hearthlight_ocsort_tuned": "ocsort-tuned",
}

logger = logging.getLogger(__name__)

STAGE_LABELS = {
    MODEL_STAGE_DETECTOR: "Detector",
    MODEL_STAGE_TRACKER: "Tracker",
    MODEL_STAGE_REID: "Person ReID",
    MODEL_STAGE_ANOMALY_STAGE_1: "Heuristic Filter",
    MODEL_STAGE_ANOMALY_STAGE_2: "Anomaly Detection",
}


def is_operator_stage(stage: str) -> bool:
    return stage in OPERATOR_MODEL_STAGES


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = OmegaConf.load(path)
    if raw is None:
        return {}
    return OmegaConf.to_container(raw, resolve=True)  # type: ignore[return-value]


def _load_upstream_master_catalog() -> dict[str, Any]:
    try:
        catalog_module = importlib.import_module(f"{MODEL_ZOO_PACKAGE_NAME}.catalog")
    except ModuleNotFoundError:
        return {}
    loader = getattr(catalog_module, "load_master_catalog", None)
    if loader is None:
        return {}
    try:
        loaded = loader()
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.warning("Failed to load hearthlight_model_zoo master catalog: %s", exc)
        return {}
    if not isinstance(loaded, dict):
        return {}
    return loaded


def _load_artifact_classes(artifact_ref: str | None) -> list[str]:
    if not artifact_ref:
        return []
    try:
        artifacts_module = importlib.import_module(f"{MODEL_ZOO_PACKAGE_NAME}.artifacts")
    except ModuleNotFoundError:
        return []
    getter = getattr(artifacts_module, "get_artifact_spec", None)
    if getter is None:
        return []
    try:
        spec = getter(str(artifact_ref))
    except Exception:
        return []
    return [str(item).strip() for item in getattr(spec, "classes", ()) if str(item).strip()]


def get_registration_capabilities(registration: dict[str, Any]) -> dict[str, Any]:
    capabilities = dict(registration.get("capabilities") or {})
    stage = str(registration.get("stage") or "").strip().lower()
    if stage == MODEL_STAGE_DETECTOR and not any(
        isinstance(capabilities.get(key), list) and capabilities.get(key)
        for key in ("classes", "detector_classes")
    ):
        artifact_classes = _load_artifact_classes(registration.get("artifact_ref"))
        if artifact_classes:
            capabilities["classes"] = artifact_classes
    return capabilities


def _normalize_registrations(
    registrations: dict[str, Any],
    *,
    stage: str,
    source_path: str,
) -> dict[str, dict[str, Any]]:
    normalized = {}
    for model_key, registration in registrations.items():
        entry = dict(registration or {})
        entry.setdefault("stage", stage)
        entry.setdefault("adapter", model_key)
        entry["capabilities"] = get_registration_capabilities(entry)
        entry.setdefault("runtime", {})
        entry.setdefault("healthcheck", {})
        entry.setdefault("resource_profile", {})
        entry.setdefault("requires_gpu", False)
        entry.setdefault("fallback_model_key", None)
        entry.setdefault("source_path", source_path)
        normalized[model_key] = entry
    return normalized


def load_model_registries(registry_dir: Path | None = None) -> dict[str, dict[str, dict[str, Any]]]:
    from .plugin_loader import load_plugin_catalog

    if registry_dir is not None:
        plugin_root = registry_dir.parent.parent / "plugins"
        if not plugin_root.exists():
            upstream_catalog = _load_upstream_master_catalog()
            upstream_models = upstream_catalog.get("models") if isinstance(upstream_catalog, dict) else {}
            registries: dict[str, dict[str, dict[str, Any]]] = {}
            for stage, filename in REGISTRY_FILE_MAP.items():
                normalized = {}
                if isinstance(upstream_models, dict):
                    normalized.update(
                        _normalize_registrations(
                            dict(upstream_models.get(stage) or {}),
                            stage=stage,
                            source_path=MODEL_ZOO_MASTER_CATALOG_SOURCE,
                        )
                    )
                normalized.update(
                    _normalize_registrations(
                        _load_yaml(registry_dir / filename),
                        stage=stage,
                        source_path=str(registry_dir / filename),
                    )
                )
                registries[stage] = normalized
            return registries

    upstream_catalog = _load_upstream_master_catalog()
    plugin_catalog = load_plugin_catalog(
        plugin_root=(registry_dir.parent.parent / "plugins") if registry_dir is not None else None,
        upstream_model_catalog=upstream_catalog,
    )
    registries: dict[str, dict[str, dict[str, Any]]] = {}
    for stage in REGISTRY_FILE_MAP:
        normalized = {}
        for model_key, registration in dict(plugin_catalog.get("models", {}).get(stage) or {}).items():
            entry = dict(registration or {})
            entry["capabilities"] = get_registration_capabilities(entry)
            entry.setdefault("runtime", {})
            entry.setdefault("healthcheck", {})
            entry.setdefault("resource_profile", {})
            entry.setdefault("requires_gpu", False)
            entry.setdefault("fallback_model_key", None)
            normalized[model_key] = entry
        registries[stage] = normalized
    return registries


def load_model_bindings(bindings_path: Path | None = None) -> dict[str, Any]:
    bindings = _load_yaml(bindings_path or MODEL_BINDINGS_PATH)
    defaults = dict(bindings.get("defaults") or {})
    return {"defaults": defaults}


def load_mounted_models(mounted_models_path: Path | None = None) -> dict[str, list[str]]:
    mounted = _load_yaml(mounted_models_path or MOUNTED_MODELS_PATH)
    raw = dict(mounted.get("mounted") or {})
    normalized: dict[str, list[str]] = {stage: [] for stage in OPERATOR_MODEL_STAGES}
    for stage in OPERATOR_MODEL_STAGES:
        values = raw.get(stage) or []
        if not isinstance(values, list):
            continue
        seen: list[str] = []
        for value in values:
            model_key = str(value or "").strip()
            if model_key and model_key not in seen:
                seen.append(model_key)
        normalized[stage] = seen
    return normalized


def persist_mounted_models(mounted_models: dict[str, list[str]]):
    payload = {
        "mounted": {
            stage: list(mounted_models.get(stage) or [])
            for stage in OPERATOR_MODEL_STAGES
        }
    }
    MOUNTED_MODELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    OmegaConf.save(config=OmegaConf.create(payload), f=str(MOUNTED_MODELS_PATH))


def build_effective_mounted_models(
    bundle: dict[str, Any],
    mounted_models: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    requested = mounted_models or load_mounted_models()
    defaults = dict(bundle.get("bindings", {}).get("defaults") or {})
    effective: dict[str, list[str]] = {stage: [] for stage in OPERATOR_MODEL_STAGES}
    for stage in OPERATOR_MODEL_STAGES:
        available = bundle.get("models", {}).get(stage, {})
        seen: list[str] = []
        for model_key in list(requested.get(stage) or []) + [defaults.get(stage)]:
            normalized = str(model_key or "").strip()
            if normalized and normalized in available and normalized not in seen:
                seen.append(normalized)
        if not seen:
            fallback_key = defaults.get(stage)
            if fallback_key and fallback_key in available:
                seen.append(fallback_key)
        effective[stage] = seen
    return effective


def ensure_mounted_model_key(
    bundle: dict[str, Any],
    mounted_models: dict[str, list[str]],
    stage: str,
    model_key: str | None,
) -> None:
    if not model_key:
        return
    normalized_stage = normalize_binding_stage(stage)
    registration = get_registration(bundle, normalized_stage, model_key)
    if registration is None:
        raise ValueError(f"unknown {normalized_stage} model binding {model_key}")
    mounted_stage = mounted_models.setdefault(normalized_stage, [])
    if model_key not in mounted_stage:
        mounted_stage.append(model_key)


def collect_required_mounted_models(
    bundle: dict[str, Any],
    source_rows: list,
    *,
    defaults: dict[str, str | None] | None = None,
) -> dict[str, set[str]]:
    resolved_defaults = defaults or build_default_bindings(bundle)
    required: dict[str, set[str]] = {
        stage: set() for stage in OPERATOR_MODEL_STAGES
    }
    for stage, model_key in resolved_defaults.items():
        if stage in required and model_key:
            required[stage].add(model_key)
    for source_row in source_rows:
        for stage, model_key in build_source_binding_overrides(source_row).items():
            if stage in required and model_key:
                required[stage].add(model_key)
    return required


def load_registry_bundle() -> dict[str, Any]:
    bundle = {
        "models": load_model_registries(),
        "bindings": load_model_bindings(),
    }
    bundle["mounted_models"] = build_effective_mounted_models(bundle, load_mounted_models())
    from .plugin_loader import load_plugin_catalog

    bundle["plugin_catalog"] = load_plugin_catalog(
        upstream_model_catalog=_load_upstream_master_catalog(),
    )
    return bundle


def _read_model_zoo_direct_url() -> dict[str, Any]:
    try:
        distribution = metadata.distribution(MODEL_ZOO_PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        return {}
    direct_url_text = None
    try:
        direct_url_text = distribution.read_text("direct_url.json")
    except Exception:
        direct_url_text = None
    if not direct_url_text:
        return {}
    try:
        loaded = json.loads(direct_url_text)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _find_model_zoo_requirement_pin() -> str | None:
    for relative_path in MODEL_ZOO_REQUIREMENT_PATHS:
        requirement_path = REPO_ROOT / relative_path
        if not requirement_path.exists():
            continue
        try:
            lines = requirement_path.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            match = MODEL_ZOO_COMMIT_PATTERN.search(line.strip())
            if match:
                return match.group("commit")
    return None


def get_model_zoo_source_info() -> dict[str, Any]:
    source_info: dict[str, Any] = {
        "package_name": MODEL_ZOO_PACKAGE_NAME,
        "version": None,
        "repository_url": MODEL_ZOO_REPOSITORY_URL,
        "commit_sha": None,
        "commit_short": None,
        "resolved_from": None,
        "catalog_available": bool(_load_upstream_master_catalog()),
    }

    try:
        distribution = metadata.distribution(MODEL_ZOO_PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        distribution = None
    if distribution is not None:
        source_info["version"] = distribution.version

    direct_url = _read_model_zoo_direct_url()
    vcs_info = direct_url.get("vcs_info") if isinstance(direct_url, dict) else {}
    commit_sha = None
    if isinstance(vcs_info, dict):
        commit_sha = vcs_info.get("commit_id") or vcs_info.get("requested_revision")
    if commit_sha:
        source_info["commit_sha"] = str(commit_sha)
        source_info["commit_short"] = str(commit_sha)[:8]
        source_info["resolved_from"] = "installed_package"
        url = direct_url.get("url")
        if isinstance(url, str) and url:
            source_info["repository_url"] = url
        return source_info

    pinned_commit = _find_model_zoo_requirement_pin()
    if pinned_commit:
        source_info["commit_sha"] = pinned_commit
        source_info["commit_short"] = pinned_commit[:8]
        source_info["resolved_from"] = "requirements_pin"
    return source_info


def _titleize_token(token: str) -> str:
    lowered = token.lower()
    if lowered in {"cpu", "gpu", "fp16", "fp32", "onnx", "yaml", "json"}:
        return lowered.upper()
    if lowered == "reid":
        return "ReID"
    if lowered == "yolox":
        return "YOLOX"
    if lowered == "bytetrack":
        return "ByteTrack"
    if lowered == "botsort":
        return "BoT-SORT"
    if lowered == "ocsort":
        return "OC-SORT"
    if lowered == "strongsort":
        return "StrongSORT"
    if lowered == "transreid":
        return "TransReID"
    if lowered == "vlm":
        return "VLM"
    if lowered == "siglip":
        return "SigLIP"
    if lowered == "smolvlm":
        return "SmolVLM"
    if lowered == "mlx":
        return "MLX"
    if lowered == "rtmo":
        return "RTMO"
    if len(token) == 1:
        return token.upper()
    return token.replace("_", " ").title()


def build_model_display_name(stage: str, model_key: str, registration: dict[str, Any]) -> str:
    runtime = dict(registration.get("runtime") or {})
    artifact_ref = str(registration.get("artifact_ref") or "").strip()
    adapter = str(registration.get("adapter") or "").strip()

    if stage == MODEL_STAGE_DETECTOR:
        if artifact_ref.startswith("yolox-"):
            size = artifact_ref.split("-", 1)[1]
            size_label = {
                "nano": "Nano",
                "tiny": "Tiny",
                "s": "Small",
                "m": "Medium",
                "l": "Large",
                "x": "Extra Large",
            }.get(size.lower(), _titleize_token(size))
            device = str(runtime.get("device") or "").strip().lower()
            if device.startswith("cuda"):
                return f"YOLOX {size_label} (GPU)"
            if device == "cpu":
                return f"YOLOX {size_label} (CPU)"
            return f"YOLOX {size_label}"
        if "yolox" in adapter:
            return "YOLOX Detector"
    elif stage == MODEL_STAGE_TRACKER:
        tracker_name = str(runtime.get("tracker_name") or artifact_ref or model_key).strip()
        tracker_label_map = {
            "bytetrack": "ByteTrack",
            "bytetrack-s": "ByteTrack Small",
            "bytetrack-balanced": "ByteTrack Balanced",
            "botsort": "BoT-SORT",
            "ocsort": "OC-SORT",
            "strongsort": "StrongSORT",
            "cmtrack": "CMTrack",
            "ocsort-tuned": "OC-SORT Tuned",
        }
        if tracker_name in tracker_label_map:
            return tracker_label_map[tracker_name]
    elif stage == MODEL_STAGE_REID:
        if "transreid" in artifact_ref or "transreid" in adapter:
            if "hybrid_bag" in adapter:
                return "TransReID Person + Hybrid Bag"
            return "TransReID"
    elif stage == MODEL_STAGE_ANOMALY_STAGE_1:
        if adapter == "siglip_stage_1":
            backend = str(runtime.get("backend") or "").strip().lower()
            if backend == "mlx":
                return "SigLIP Stage 1 (MLX)"
            if str(runtime.get("device") or "").strip().lower().startswith("cuda"):
                return "SigLIP Stage 1 (CUDA)"
            return "SigLIP Stage 1 (CPU)"
        if adapter == "heuristic_presence_stage_1":
            return "Heuristic Presence Stage 1"
    elif stage == MODEL_STAGE_ANOMALY_STAGE_2:
        if adapter == "smolvlm_stage_2":
            backend = str(runtime.get("backend") or "").strip().lower()
            if backend == "mlx":
                return "SmolVLM Stage 2 (MLX)"
            if str(runtime.get("device") or "").strip().lower().startswith("cuda"):
                return "SmolVLM Stage 2 (CUDA)"
            return "SmolVLM Stage 2 (CPU)"
        if adapter == "prompt_rules_stage_2":
            return "Prompt Rules Stage 2"
        if adapter == "passthrough_stage_2":
            return "Pass-Through Stage 2"
        if adapter == "vlm_anomaly_demo_stage_2":
            return "VLM Anomaly Demo Stage 2"
        if adapter == "claude_compatible_stage_2":
            return "Claude-Compatible Anomaly API"
        if adapter == "openai_compatible_stage_2":
            provider = str(runtime.get("provider") or "").strip().lower()
            if provider == "lm_studio":
                return "LM Studio"
            if provider == "lauretta":
                return "Lauretta API"
            if provider == "openai":
                return "Chatgpt"
            return "OpenAI-Compatible API"
        if adapter == "claude_stage_2":
            return "Claude"

    cleaned_key = model_key.removeprefix("builtin_").replace("-", " ").replace("_", " ")
    parts = [part for part in cleaned_key.split() if part]
    if not parts:
        return STAGE_LABELS.get(stage, "Model")
    return " ".join(_titleize_token(part) for part in parts)


def _build_model_option_display_name(model_key: str, registration: dict[str, Any], *, option_origin: str) -> str:
    stage = str(registration.get("stage") or "").strip().lower()
    return build_model_display_name(stage, model_key, registration)


def build_model_option_catalog(bundle: dict[str, Any]) -> dict[str, Any]:
    upstream_catalog = _load_upstream_master_catalog()
    upstream_models = upstream_catalog.get("models") if isinstance(upstream_catalog, dict) else {}
    mounted_models = build_effective_mounted_models(bundle, bundle.get("mounted_models"))
    stages = []
    for stage in OPERATOR_MODEL_STAGES:
        stage_models = bundle.get("models", {}).get(stage, {})
        upstream_stage = dict(upstream_models.get(stage) or {}) if isinstance(upstream_models, dict) else {}
        options = []
        model_zoo_option_count = 0
        local_option_count = 0
        local_override_count = 0
        mounted_option_count = 0
        for model_key in sorted(stage_models):
            registration = dict(stage_models.get(model_key) or {})
            source_path = registration.get("source_path")
            if source_path == MODEL_ZOO_MASTER_CATALOG_SOURCE:
                option_origin = "model_zoo"
                model_zoo_option_count += 1
            elif model_key in upstream_stage:
                option_origin = "local_override"
                local_override_count += 1
                local_option_count += 1
            else:
                option_origin = "local_registry"
                local_option_count += 1
            is_mounted = model_key in set(mounted_models.get(stage) or [])
            if is_mounted:
                mounted_option_count += 1
            options.append(
                {
                    "model_key": model_key,
                    "display_name": _build_model_option_display_name(
                        model_key,
                        registration,
                        option_origin=option_origin,
                    ),
                    "stage": stage,
                    "adapter": registration.get("adapter"),
                    "artifact_ref": registration.get("artifact_ref"),
                    "runtime": dict(registration.get("runtime") or {}),
                    "capabilities": get_registration_capabilities(registration),
                    "healthcheck": dict(registration.get("healthcheck") or {}),
                    "requires_gpu": bool(registration.get("requires_gpu")),
                    "resource_profile": dict(registration.get("resource_profile") or {}),
                    "source_path": source_path,
                    "option_origin": option_origin,
                    "comes_from_model_zoo": option_origin == "model_zoo",
                    "overrides_model_zoo": option_origin == "local_override",
                    "is_mounted": is_mounted,
                }
            )
        stages.append(
            {
                "stage": stage,
                "options": options,
                "model_zoo_option_count": model_zoo_option_count,
                "local_option_count": local_option_count,
                "local_override_count": local_override_count,
                "mounted_option_count": mounted_option_count,
            }
        )
    return {
        "model_zoo": get_model_zoo_source_info(),
        "mounted_models": mounted_models,
        "stages": stages,
    }


def normalize_binding_stage(stage: str) -> str:
    normalized = stage.strip().lower()
    if normalized not in MODEL_BINDING_STAGES:
        raise ValueError(f"unknown model binding stage {stage}")
    return normalized


def get_stage_field_name(stage: str) -> str:
    return STAGE_FIELD_MAP[normalize_binding_stage(stage)]


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "items"):
        return {key: mapped for key, mapped in value.items()}
    return {}


def extract_runtime_default_bindings(runtime_model_bindings: Any) -> dict[str, str | None]:
    runtime_bindings = _coerce_mapping(runtime_model_bindings)
    runtime_defaults = _coerce_mapping(runtime_bindings.get("defaults"))
    normalized_defaults = {}
    for stage, model_key in runtime_defaults.items():
        stage_name = str(stage).strip().lower()
        if stage_name not in MODEL_BINDING_STAGES:
            continue
        normalized_defaults[stage_name] = None if model_key is None else str(model_key)
    return normalized_defaults


def resolve_default_model_key(
    bundle: dict[str, Any],
    stage: str,
    model_key: str | None,
    *,
    has_gpu: bool | None = None,
) -> str | None:
    if model_key is None or has_gpu is not False:
        return model_key
    normalized_stage = normalize_binding_stage(stage)
    registration = get_registration(bundle, normalized_stage, model_key)
    if registration is None or not registration.get("requires_gpu"):
        return model_key

    fallback_key = registration.get("fallback_model_key")
    if fallback_key:
        fallback_registration = get_registration(bundle, normalized_stage, fallback_key)
        if fallback_registration is not None and not fallback_registration.get("requires_gpu"):
            return fallback_key

    for candidate_key in sorted(bundle.get("models", {}).get(normalized_stage, {})):
        candidate = get_registration(bundle, normalized_stage, candidate_key)
        if candidate is None or candidate.get("requires_gpu"):
            continue
        if candidate.get("adapter") == registration.get("adapter"):
            return candidate_key
    return model_key


def resolve_model_key_for_gpu(
    bundle: dict[str, Any],
    stage: str,
    model_key: str | None,
) -> str | None:
    """If model_key is a CPU fallback and a GPU parent exists, return the GPU parent."""
    if model_key is None:
        return model_key
    normalized_stage = normalize_binding_stage(stage)
    registration = get_registration(bundle, normalized_stage, model_key)
    if registration is None or registration.get("requires_gpu"):
        return model_key  # already a GPU model or unknown
    stage_registrations = bundle.get("models", {}).get(normalized_stage, {})
    for candidate_key, candidate_reg in stage_registrations.items():
        if (candidate_reg.get("fallback_model_key") == model_key
                and candidate_reg.get("requires_gpu")):
            return candidate_key
    return model_key


def build_default_bindings(
    bundle: dict[str, Any],
    *,
    has_gpu: bool | None = None,
    runtime_model_bindings: Any = None,
) -> dict[str, str | None]:
    defaults = {
        stage: None for stage in MODEL_BINDING_STAGES
    }
    defaults.update(bundle.get("bindings", {}).get("defaults", {}))
    defaults.update(extract_runtime_default_bindings(runtime_model_bindings))
    if has_gpu is False and platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"}:
        for stage in (MODEL_STAGE_ANOMALY_STAGE_1, MODEL_STAGE_ANOMALY_STAGE_2):
            stage_models = bundle.get("models", {}).get(stage, {})
            for candidate_key, candidate in stage_models.items():
                if candidate.get("default_for_backend") == "mlx":
                    defaults[stage] = candidate_key
                    break
    if has_gpu is False:
        for stage in MODEL_BINDING_STAGES:
            defaults[stage] = resolve_default_model_key(
                bundle,
                stage,
                defaults.get(stage),
                has_gpu=has_gpu,
            )
    elif has_gpu is True:
        for stage in MODEL_BINDING_STAGES:
            defaults[stage] = resolve_model_key_for_gpu(bundle, stage, defaults.get(stage))
    return defaults


def build_source_binding_overrides(source_row) -> dict[str, str | None]:
    return {
        stage: getattr(source_row, get_stage_field_name(stage), None)
        for stage in MODEL_BINDING_STAGES
    }


def resolve_bindings_for_source(
    source_row,
    defaults: dict[str, str | None],
) -> dict[str, str | None]:
    resolved = {
        stage: defaults.get(stage)
        for stage in MODEL_BINDING_STAGES
    }
    for stage, override in build_source_binding_overrides(source_row).items():
        if override:
            resolved[stage] = override
    return resolved


def get_registration(bundle: dict[str, Any], stage: str, model_key: str | None) -> dict[str, Any] | None:
    if model_key is None:
        return None
    return bundle.get("models", {}).get(normalize_binding_stage(stage), {}).get(model_key)


def resolve_tracker_name(
    registration: dict[str, Any] | None,
    model_key: str | None,
    legacy_tracker_name: str | None = None,
) -> str | None:
    if registration is not None:
        runtime = registration.get("runtime") or {}
        tracker_name = runtime.get("tracker_name") or registration.get("artifact_ref")
        if tracker_name:
            return str(tracker_name)
    if legacy_tracker_name:
        return str(legacy_tracker_name)
    if model_key is None:
        return None
    if model_key in LEGACY_TRACKER_NAME_MAP:
        return LEGACY_TRACKER_NAME_MAP[model_key]
    if model_key.startswith("builtin_"):
        return model_key.removeprefix("builtin_")
    return model_key


def registration_supports_source(registration: dict[str, Any], *, source_kind: str, tasks: list[str]) -> bool:
    capabilities = registration.get("capabilities") or {}
    allowed_source_kinds = {
        str(kind).strip()
        for kind in capabilities.get("source_kinds", [])
    }
    if allowed_source_kinds and source_kind not in allowed_source_kinds:
        return False
    allowed_tasks = {
        str(task).strip().upper()
        for task in capabilities.get("tasks", [])
    }
    normalized_tasks = {str(task).strip().upper() for task in tasks}
    if allowed_tasks and normalized_tasks.difference(allowed_tasks):
        return False
    return True


def validate_source_bindings(
    bundle: dict[str, Any],
    source_row,
    defaults: dict[str, str | None],
) -> list[str]:
    errors = []
    resolved = resolve_bindings_for_source(source_row, defaults)
    for stage, model_key in resolved.items():
        registration = get_registration(bundle, stage, model_key)
        if registration is None:
            errors.append(f"{source_row.label}: missing {stage} model registration {model_key}")
            continue
        source_tasks = [str(task).strip().upper() for task in list(source_row.tasks)]
        relevant_tasks = sorted(set(source_tasks).intersection(get_required_tasks_for_stage(stage)))
        if not registration_supports_source(
            registration,
            source_kind=source_row.kind,
            tasks=relevant_tasks,
        ):
            errors.append(
                f"{source_row.label}: {stage} model {model_key} is incompatible with source kind/tasks"
            )
    return errors


def is_registration_available(registration: dict[str, Any]) -> tuple[bool, str | None]:
    healthcheck = registration.get("healthcheck") or {}
    required_env_vars = [
        str(name).strip()
        for name in list(healthcheck.get("required_env_vars") or [])
        if str(name).strip()
    ]
    missing_env_vars = [name for name in required_env_vars if not os.environ.get(name, "").strip()]
    if missing_env_vars:
        joined = ", ".join(missing_env_vars)
        return False, f"missing required env vars: {joined}"
    import_path = healthcheck.get("import_path")
    if import_path:
        try:
            spec = find_spec(import_path)
        except ModuleNotFoundError:
            spec = None
        if spec is None:
            return False, f"import path {import_path} is unavailable"
    return True, None


def build_model_health(bundle: dict[str, Any], *, has_gpu: bool) -> dict[str, dict[str, Any]]:
    health = {}
    for stage, registrations in bundle.get("models", {}).items():
        for model_key, registration in registrations.items():
            available, detail = is_registration_available(registration)
            if registration.get("requires_gpu") and not has_gpu:
                available = False
                detail = "gpu is required but unavailable"
            health[model_key] = {
                "model_key": model_key,
                "stage": stage,
                "adapter": registration.get("adapter"),
                "healthy": bool(available),
                "detail": detail,
                "requires_gpu": bool(registration.get("requires_gpu")),
            }
    return health


def get_required_tasks_for_stage(stage: str) -> set[str]:
    if stage == MODEL_STAGE_DETECTOR:
        return {Tasks.PERSON, Tasks.BAG}
    if stage == MODEL_STAGE_TRACKER:
        return {Tasks.PERSON, Tasks.BAG}
    if stage == MODEL_STAGE_REID:
        return {Tasks.PERSON, Tasks.BAG}
    return {Tasks.PERSON, Tasks.BAG}


def build_runtime_binding_block(
    source_rows: list,
    bundle: dict[str, Any],
    *,
    defaults: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    defaults = defaults or build_default_bindings(bundle)
    source_bindings = {}
    for source_row in source_rows:
        if getattr(source_row, "id", None) is None:
            continue
        source_bindings[str(source_row.id)] = resolve_bindings_for_source(
            source_row, defaults
        )
    return {
        "defaults": {
            stage: defaults.get(stage)
            for stage in MODEL_BINDING_STAGES
        },
        "sources": source_bindings,
    }


def sync_registry_bundle_to_db(db, bundle: dict[str, Any], sql_models, source_rows: list | None = None):
    active_model_keys: set[str] = set()
    for stage, registrations in bundle.get("models", {}).items():
        for model_key, registration in registrations.items():
            active_model_keys.add(model_key)
            row = (
                db.query(sql_models.ModelRegistration)
                .filter(sql_models.ModelRegistration.model_key == model_key)
                .order_by(sql_models.ModelRegistration.id.asc())
                .first()
            )
            if row is None:
                row = sql_models.ModelRegistration(model_key=model_key)
                db.add(row)
            row.stage = stage
            row.adapter = registration.get("adapter")
            row.runtime_json = OmegaConf.to_yaml(OmegaConf.create(registration.get("runtime") or {}))
            row.artifact_ref = registration.get("artifact_ref")
            row.capability_json = OmegaConf.to_yaml(OmegaConf.create(registration.get("capabilities") or {}))
            row.healthcheck_json = OmegaConf.to_yaml(OmegaConf.create(registration.get("healthcheck") or {}))
            row.requires_gpu = bool(registration.get("requires_gpu"))
            row.resource_profile_json = OmegaConf.to_yaml(OmegaConf.create(registration.get("resource_profile") or {}))
            row.source_path = str(registration.get("source_path") or (REGISTRY_DIR / REGISTRY_FILE_MAP[stage]))
            row.is_deleted = False
            row.deleted_at = None

    defaults = build_default_bindings(bundle)
    for stage, model_key in defaults.items():
        row = (
            db.query(sql_models.ModelBindingTemplate)
            .filter_by(stage=stage, source_template_id=None, is_deleted=False)
            .first()
        )
        if row is None:
            row = sql_models.ModelBindingTemplate(stage=stage, source_template_id=None)
            db.add(row)
        row.binding_scope = "default"
        row.model_key = model_key
        row.is_deleted = False
        row.deleted_at = None

    source_rows = source_rows or []
    active_source_ids = {row.id for row in source_rows if row.id is not None}
    for source_row in source_rows:
        if source_row.id is None:
            continue
        for stage, model_key in build_source_binding_overrides(source_row).items():
            row = (
                db.query(sql_models.ModelBindingTemplate)
                .filter_by(stage=stage, source_template_id=source_row.id, is_deleted=False)
                .first()
            )
            if row is None:
                row = sql_models.ModelBindingTemplate(stage=stage, source_template_id=source_row.id)
                db.add(row)
            row.binding_scope = "source"
            row.model_key = model_key
            row.is_deleted = False
            row.deleted_at = None

    for row in db.query(sql_models.ModelBindingTemplate).filter_by(binding_scope="source").all():
        if row.source_template_id not in active_source_ids:
            row.is_deleted = True

    for row in db.query(sql_models.ModelRegistration).all():
        if row.model_key in active_model_keys:
            continue
        row.is_deleted = True

def parse_yaml_text(raw_yaml: str | None) -> dict[str, Any]:
    if not raw_yaml:
        return {}
    return OmegaConf.to_container(OmegaConf.create(raw_yaml), resolve=True)  # type: ignore[return-value]
