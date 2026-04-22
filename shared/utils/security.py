from __future__ import annotations

import re
from pathlib import Path

from ..constants import IncidentStatus


SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")

VALID_INCIDENT_STATUS_TRANSITIONS = {
    IncidentStatus.UNCONFIRMED: {
        IncidentStatus.CONFIRMED,
        IncidentStatus.PENDING_RESOLVE,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.CONFIRMED: {
        IncidentStatus.IN_PROGRESS,
        IncidentStatus.PENDING_RESOLVE,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.IN_PROGRESS: {
        IncidentStatus.PENDING_RESOLVE,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.PENDING_RESOLVE: {
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.RESOLVED: set(),
}


def sanitize_identifier(value: str, fallback: str = "item", max_length: int = 64) -> str:
    cleaned = SAFE_COMPONENT_RE.sub("_", str(value)).strip("._-")
    cleaned = cleaned[:max_length]
    return cleaned or fallback


def resolve_safe_child_path(
    base_dir: str | Path, user_component: str, fallback: str = "item"
) -> Path:
    base_path = Path(base_dir).resolve()
    child_name = sanitize_identifier(user_component, fallback=fallback)
    child_path = (base_path / child_name).resolve()
    if child_path.parent != base_path:
        raise ValueError("resolved path escapes base directory")
    return child_path


def is_valid_incident_status_transition(current_status: str, new_status: str) -> bool:
    if current_status == new_status:
        return True
    allowed = VALID_INCIDENT_STATUS_TRANSITIONS.get(current_status, set())
    return new_status in allowed
