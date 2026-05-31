from __future__ import annotations

from collections import OrderedDict
from typing import Any

from omegaconf import OmegaConf
from sqlalchemy import inspect, text

from ..database.database import get_engine
from ..models import SQLModels
from .model_registry import (
    MODEL_STAGE_DETECTOR,
    build_default_bindings,
    get_registration,
    resolve_bindings_for_source,
)

ALERT_SIGNAL_FAMILY_DETECTOR = "detector"
ALERT_SIGNAL_FAMILY_ANOMALY_OBJECT = "anomaly_object"
ALERT_SIGNAL_FAMILY_ANOMALY_ACTIVITY = "anomaly_activity"
ALERT_SIGNAL_FAMILIES = {
    ALERT_SIGNAL_FAMILY_DETECTOR,
    ALERT_SIGNAL_FAMILY_ANOMALY_OBJECT,
    ALERT_SIGNAL_FAMILY_ANOMALY_ACTIVITY,
}

ALERT_LEVEL_LOW = "low"
ALERT_LEVEL_MEDIUM = "medium"
ALERT_LEVEL_HIGH = "high"
ALERT_LEVELS = {
    ALERT_LEVEL_LOW,
    ALERT_LEVEL_MEDIUM,
    ALERT_LEVEL_HIGH,
}
TRIGGER_KEY_ALERT_RULE = "alert_rule_trigger"

DETECTOR_CLASS_ALIAS_MAP = {
    "person": "PERSON",
    "people": "PERSON",
    "pedestrian": "PERSON",
    "bag": "BAG",
    "backpack": "BAG",
    "handbag": "BAG",
    "suitcase": "BAG",
    "luggage": "BAG",
}

DETECTOR_TRIGGER_FAMILY_ORDER = ("PERSON", "BAG")


def ensure_alert_rule_tables() -> None:
    engine = get_engine()
    SQLModels.Base.metadata.create_all(
        bind=engine,
        tables=[
            SQLModels.TriggerRule.__table__,
            SQLModels.AlertIncident.__table__,
        ],
        checkfirst=True,
    )
    inspector = inspect(engine)
    column_names = {
        column["name"]
        for column in inspector.get_columns("trigger_rule", schema="control")
    }
    alterations: list[str] = []
    if "trigger_key" not in column_names:
        alterations.append("ADD COLUMN trigger_key VARCHAR(128) NOT NULL DEFAULT 'alert_rule_trigger'")
    if "source_ids_json" not in column_names:
        alterations.append("ADD COLUMN source_ids_json TEXT")
    if "sort_order" not in column_names:
        alterations.append("ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
    if "rule_label" not in column_names:
        alterations.append("ADD COLUMN rule_label VARCHAR(255)")
    if "rule_kind" not in column_names:
        alterations.append("ADD COLUMN rule_kind VARCHAR(32) NOT NULL DEFAULT 'detector'")
    if "anomaly_target_kind" not in column_names:
        alterations.append("ADD COLUMN anomaly_target_kind VARCHAR(32)")
    if "anomaly_cutoff" not in column_names:
        alterations.append("ADD COLUMN anomaly_cutoff INTEGER")
    if "delivery_target_ids_json" not in column_names:
        alterations.append("ADD COLUMN delivery_target_ids_json TEXT")
    if "metadata_json" not in column_names:
        alterations.append("ADD COLUMN metadata_json TEXT")
    if alterations:
        with engine.begin() as conn:
            for alteration in alterations:
                conn.execute(text(f"ALTER TABLE control.trigger_rule {alteration}"))


def _normalize_detector_target(raw_target: str) -> str | None:
    normalized = str(raw_target or "").strip().lower()
    if not normalized:
        return None
    return DETECTOR_CLASS_ALIAS_MAP.get(normalized)


def _load_artifact_classes(artifact_ref: str | None) -> list[str]:
    if not artifact_ref:
        return []
    try:
        from hearthlight_model_zoo.artifacts import get_artifact_spec
    except ModuleNotFoundError:
        return []
    try:
        spec = get_artifact_spec(str(artifact_ref))
    except KeyError:
        return []
    return [str(item).strip() for item in getattr(spec, "classes", ()) if str(item).strip()]


def get_detector_rule_targets(registration: dict[str, Any] | None) -> list[dict[str, str]]:
    if registration is None:
        return []
    capabilities = dict(registration.get("capabilities") or {})
    raw_targets = []
    for key in ("alert_rule_targets", "classes", "detector_classes"):
        values = capabilities.get(key)
        if isinstance(values, list):
            raw_targets.extend(values)
    if not raw_targets:
        raw_targets.extend(_load_artifact_classes(registration.get("artifact_ref")))
    normalized_targets: OrderedDict[str, list[str]] = OrderedDict()
    for raw_target in raw_targets:
        cleaned_target = str(raw_target).strip()
        normalized = _normalize_detector_target(cleaned_target)
        if normalized is None:
            continue
        if normalized not in normalized_targets:
            normalized_targets[normalized] = []
        lowered_target = cleaned_target.lower()
        if lowered_target and lowered_target not in normalized_targets[normalized]:
            normalized_targets[normalized].append(lowered_target)
    options = []
    for key in DETECTOR_TRIGGER_FAMILY_ORDER:
        if key not in normalized_targets:
            continue
        raw_matches = normalized_targets[key]
        description = None
        if raw_matches:
            qualifier = "class" if len(raw_matches) == 1 else "classes"
            description = f"Matches detector {qualifier}: {', '.join(raw_matches)}"
        options.append(
            {
                "key": key,
                "label": key,
                "description": description,
            }
        )
    return options


def parse_anomaly_type_prompt_yaml(raw_yaml: str | None) -> dict[str, list[str]]:
    if not raw_yaml or not raw_yaml.strip():
        return {"anomaly_object_list": [], "anomaly_activity_list": []}
    parsed = OmegaConf.to_container(OmegaConf.create(raw_yaml), resolve=True)
    if not isinstance(parsed, dict):
        return {"anomaly_object_list": [], "anomaly_activity_list": []}
    result = {}
    for field_name in ("anomaly_object_list", "anomaly_activity_list"):
        values = parsed.get(field_name) or []
        if not isinstance(values, list):
            raise ValueError(f"{field_name} must be a list")
        result[field_name] = [
            str(item).strip()
            for item in values
            if str(item).strip()
        ]
    return result


def _build_option_entries(values: list[str]) -> list[dict[str, str]]:
    seen = OrderedDict()
    for value in values:
        normalized = str(value).strip()
        lowered = normalized.lower()
        if not normalized or lowered in seen:
            continue
        seen[lowered] = normalized
    return [{"key": value, "label": value} for value in seen.values()]


def build_alert_rule_option_catalog(
    *,
    bundle: dict[str, Any],
    source_rows: list,
    anomaly_type_yaml: str | None,
    has_gpu: bool | None = None,
) -> dict[str, Any]:
    defaults = build_default_bindings(bundle, has_gpu=has_gpu)
    try:
        anomaly_lists = parse_anomaly_type_prompt_yaml(anomaly_type_yaml)
        anomaly_options = {
            ALERT_SIGNAL_FAMILY_ANOMALY_OBJECT: {
                "signal_family": ALERT_SIGNAL_FAMILY_ANOMALY_OBJECT,
                "options": _build_option_entries(anomaly_lists["anomaly_object_list"]),
                "unavailable_reason": None,
            },
            ALERT_SIGNAL_FAMILY_ANOMALY_ACTIVITY: {
                "signal_family": ALERT_SIGNAL_FAMILY_ANOMALY_ACTIVITY,
                "options": _build_option_entries(anomaly_lists["anomaly_activity_list"]),
                "unavailable_reason": None,
            },
        }
    except Exception as exc:
        anomaly_options = {
            ALERT_SIGNAL_FAMILY_ANOMALY_OBJECT: {
                "signal_family": ALERT_SIGNAL_FAMILY_ANOMALY_OBJECT,
                "options": [],
                "unavailable_reason": f"anomaly type prompt is unavailable: {exc}",
            },
            ALERT_SIGNAL_FAMILY_ANOMALY_ACTIVITY: {
                "signal_family": ALERT_SIGNAL_FAMILY_ANOMALY_ACTIVITY,
                "options": [],
                "unavailable_reason": f"anomaly type prompt is unavailable: {exc}",
            },
        }

    sources = []
    for source_row in source_rows:
        resolved = resolve_bindings_for_source(source_row, defaults)
        detector_model_key = resolved.get(MODEL_STAGE_DETECTOR)
        detector_registration = get_registration(
            bundle, MODEL_STAGE_DETECTOR, detector_model_key
        )
        detector_targets = get_detector_rule_targets(detector_registration)
        if detector_targets:
            detector_option_group = {
                "signal_family": ALERT_SIGNAL_FAMILY_DETECTOR,
                "options": detector_targets,
                "unavailable_reason": None,
            }
        else:
            unavailable_reason = (
                "Please select and save a detector model that exposes detector classes for this source first."
                if detector_model_key
                else "Please connect and save a source with a detector model first."
            )
            detector_option_group = {
                "signal_family": ALERT_SIGNAL_FAMILY_DETECTOR,
                "options": [],
                "unavailable_reason": unavailable_reason,
            }

        sources.append(
            {
                "source_id": source_row.id,
                "source_label": source_row.label,
                "detector_model_key": detector_model_key,
                "anomaly_stage_1_model_key": resolved.get("anomaly_stage_1"),
                "anomaly_stage_2_model_key": resolved.get("anomaly_stage_2"),
                "signal_options": [
                    detector_option_group,
                    dict(anomaly_options[ALERT_SIGNAL_FAMILY_ANOMALY_OBJECT]),
                    dict(anomaly_options[ALERT_SIGNAL_FAMILY_ANOMALY_ACTIVITY]),
                ],
            }
        )
    return {"sources": sources}


def build_alert_rule_option_lookup(option_catalog: dict[str, Any]) -> dict[int, dict[str, dict[str, Any]]]:
    lookup: dict[int, dict[str, dict[str, Any]]] = {}
    for source_entry in option_catalog.get("sources", []):
        source_id = source_entry.get("source_id")
        if source_id is None:
            continue
        lookup[int(source_id)] = {}
        for signal_entry in source_entry.get("signal_options", []):
            signal_family = signal_entry.get("signal_family")
            if not signal_family:
                continue
            lookup[int(source_id)][str(signal_family)] = dict(signal_entry)
    return lookup


def resolve_alert_rule_target_label(target_key: str) -> str:
    normalized = str(target_key or "").strip()
    if normalized.upper() in {"PERSON", "BAG"}:
        return normalized.title()
    return normalized


def build_alert_incident_title(signal_family: str, target_key: str) -> str:
    target_label = resolve_alert_rule_target_label(target_key)
    normalized_family = str(signal_family or "").strip().lower()
    if normalized_family == ALERT_SIGNAL_FAMILY_DETECTOR:
        return f"Detector: {target_label}"
    if normalized_family == ALERT_SIGNAL_FAMILY_ANOMALY_ACTIVITY:
        return f"Behavior Anomaly: {target_label}"
    if normalized_family == ALERT_SIGNAL_FAMILY_ANOMALY_OBJECT:
        return f"Object Anomaly: {target_label}"
    return f"Trigger: {target_label}"


def resolve_alert_level_label(level: str) -> str:
    normalized = str(level or "").strip().lower()
    if normalized == ALERT_LEVEL_LOW:
        return "Low"
    if normalized == ALERT_LEVEL_HIGH:
        return "High"
    return "Medium"
