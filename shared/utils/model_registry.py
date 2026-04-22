from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import logging
from typing import Any

from omegaconf import OmegaConf

from ..constants import Tasks

MODEL_STAGE_DETECTOR = "detector"
MODEL_STAGE_TRACKER = "tracker"
MODEL_STAGE_REID = "reid"
MODEL_STAGE_ANOMALY = "anomaly"
MODEL_BINDING_STAGES = (
    MODEL_STAGE_DETECTOR,
    MODEL_STAGE_TRACKER,
    MODEL_STAGE_REID,
    MODEL_STAGE_ANOMALY,
)

SHARED_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = SHARED_ROOT / "configs"
REGISTRY_DIR = CONFIG_ROOT / "registries"
MODEL_BINDINGS_PATH = CONFIG_ROOT / "model_bindings.yaml"

REGISTRY_FILE_MAP = {
    MODEL_STAGE_DETECTOR: "detectors.yaml",
    MODEL_STAGE_TRACKER: "trackers.yaml",
    MODEL_STAGE_REID: "reid_models.yaml",
    MODEL_STAGE_ANOMALY: "anomaly_models.yaml",
}

STAGE_FIELD_MAP = {
    MODEL_STAGE_DETECTOR: "detector_model_key",
    MODEL_STAGE_TRACKER: "tracker_model_key",
    MODEL_STAGE_REID: "reid_model_key",
    MODEL_STAGE_ANOMALY: "anomaly_model_key",
}

LEGACY_TRACKER_NAME_MAP = {
    "builtin_cmtrack": "cmtrack",
    "builtin_ocsort": "ocsort",
}

logger = logging.getLogger(__name__)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = OmegaConf.load(path)
    if raw is None:
        return {}
    return OmegaConf.to_container(raw, resolve=True)  # type: ignore[return-value]


def load_model_registries(registry_dir: Path | None = None) -> dict[str, dict[str, dict[str, Any]]]:
    registry_root = registry_dir or REGISTRY_DIR
    registries: dict[str, dict[str, dict[str, Any]]] = {}
    for stage, filename in REGISTRY_FILE_MAP.items():
        registrations = _load_yaml(registry_root / filename)
        normalized = {}
        for model_key, registration in registrations.items():
            entry = dict(registration or {})
            entry.setdefault("stage", stage)
            entry.setdefault("adapter", model_key)
            entry.setdefault("capabilities", {})
            entry.setdefault("runtime", {})
            entry.setdefault("healthcheck", {})
            entry.setdefault("resource_profile", {})
            entry.setdefault("requires_gpu", False)
            entry.setdefault("fallback_model_key", None)
            entry.setdefault("source_path", str(registry_root / filename))
            normalized[model_key] = entry
        registries[stage] = normalized
    return registries


def load_model_bindings(bindings_path: Path | None = None) -> dict[str, Any]:
    bindings = _load_yaml(bindings_path or MODEL_BINDINGS_PATH)
    defaults = dict(bindings.get("defaults") or {})
    return {"defaults": defaults}


def load_registry_bundle() -> dict[str, Any]:
    return {
        "models": load_model_registries(),
        "bindings": load_model_bindings(),
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
    import_path = healthcheck.get("import_path")
    if import_path:
        if str(import_path).startswith("src."):
            return True, "validated by worker runtime"
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
        return {Tasks.PERSON, Tasks.BAG, Tasks.GUN}
    if stage == MODEL_STAGE_TRACKER:
        return {Tasks.PERSON, Tasks.BAG}
    if stage == MODEL_STAGE_REID:
        return {Tasks.PERSON, Tasks.BAG}
    return {Tasks.PERSON, Tasks.BAG, Tasks.GUN}


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
    for stage, registrations in bundle.get("models", {}).items():
        for model_key, registration in registrations.items():
            row = (
                db.query(sql_models.ModelRegistration)
                .filter_by(model_key=model_key, is_deleted=False)
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
            row.source_path = str(REGISTRY_DIR / REGISTRY_FILE_MAP[stage])
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

def parse_yaml_text(raw_yaml: str | None) -> dict[str, Any]:
    if not raw_yaml:
        return {}
    return OmegaConf.to_container(OmegaConf.create(raw_yaml), resolve=True)  # type: ignore[return-value]
