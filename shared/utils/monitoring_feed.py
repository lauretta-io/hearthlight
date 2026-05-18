from __future__ import annotations

import json


DEFAULT_FEED_LIMIT = 25
MAX_FEED_LIMIT = 200


def normalize_feed_limit(
    limit: int | None,
    *,
    default: int = DEFAULT_FEED_LIMIT,
    max_limit: int = MAX_FEED_LIMIT,
) -> int:
    if limit is None:
        return default
    return max(1, min(int(limit), max_limit))


def parse_serialized_json(raw_value: str | None, default_value=None):
    if not raw_value:
        return default_value
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return default_value


def infer_run_status(
    run_identifier: str,
    *,
    current_run_id: str | None,
    system_status: str,
) -> str:
    if run_identifier == current_run_id:
        return system_status
    return "completed"


def build_feed_endpoint_catalog() -> list[dict[str, str]]:
    return [
        {
            "name": "Algorithm Feed",
            "path": "/feeds/algorithm",
            "description": "Combined source, resource, trigger, entity, and anomaly output for a run.",
        },
        {
            "name": "Trigger Feed",
            "path": "/feeds/incidents",
            "description": "Trigger-only algorithm output for downstream alert consumers.",
        },
        {
            "name": "Entity Feed",
            "path": "/feeds/entities",
            "description": "Entity tracking output for downstream analytics consumers.",
        },
        {
            "name": "Monitoring Overview",
            "path": "/monitoring/overview",
            "description": "Operator-oriented monitoring summary for the current or selected run.",
        },
        {
            "name": "Model Registrations",
            "path": "/models",
            "description": "Registry-backed detector, tracker, ReID, and anomaly model inventory.",
        },
        {
            "name": "Model Bindings",
            "path": "/model-bindings",
            "description": "Resolved default and source-level model bindings for the active pipeline.",
        },
        {
            "name": "Model Health",
            "path": "/system/model-health",
            "description": "Availability and readiness state for each registered model.",
        },
        {
            "name": "Resource Events",
            "path": "/monitoring/events",
            "description": "Recent orchestration and admission-control events.",
        },
    ]
