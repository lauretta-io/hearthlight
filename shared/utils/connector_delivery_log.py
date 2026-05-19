from __future__ import annotations

from collections import deque
from datetime import datetime
from threading import Lock
from typing import Any

_DELIVERY_EVENTS: deque[dict[str, Any]] = deque(maxlen=100)
_DELIVERY_EVENTS_LOCK = Lock()


def record_connector_delivery_event(
    *,
    connector_key: str,
    connector_label: str | None,
    status: str,
    status_code: int | None = None,
    message: str | None = None,
    trigger_id: str | None = None,
    trigger_type: str | None = None,
) -> None:
    event = {
        "created_at": datetime.utcnow().isoformat(),
        "event_type": f"connector.{connector_key}.{status}",
        "severity": "error" if status == "error" else "info",
        "message": message or f"{connector_label or connector_key} delivery {status}",
        "metadata": {
            "connector_key": connector_key,
            "connector_label": connector_label,
            "status": status,
            "status_code": status_code,
            "trigger_id": trigger_id,
            "trigger_type": trigger_type,
        },
    }
    with _DELIVERY_EVENTS_LOCK:
        _DELIVERY_EVENTS.appendleft(event)


def list_connector_delivery_events(limit: int | None = None) -> list[dict[str, Any]]:
    with _DELIVERY_EVENTS_LOCK:
        events = list(_DELIVERY_EVENTS)
    if limit is None:
        return events
    return events[: max(0, int(limit))]
