from __future__ import annotations

import json
from typing import Any

from ..database.database import get_engine
from ..models import SQLModels

CONNECTOR_KEY_TELEGRAM = "telegram"
CONNECTOR_KEY_APPLE_MESSAGES = "apple_messages"
CONNECTOR_KEY_CLAUDE_API = "claude_api"
CONNECTOR_KEY_PHILIPS_HUE = "philips_hue"
CONNECTOR_KEY_MUSIC_API = "music_api"
CONNECTOR_KEY_ROBOT_ACTION = "robot_action"
ACTION_CONNECTOR_KEYS = {
    CONNECTOR_KEY_PHILIPS_HUE,
    CONNECTOR_KEY_MUSIC_API,
    CONNECTOR_KEY_ROBOT_ACTION,
}
CONNECTOR_KEY_GOVEE = "govee"
MASKED_SECRET_VALUE = "********"
SECRET_CONFIG_KEYS = {
    "auth_token",
    "bot_token",
    "bearer_token",
    "secret",
    "api_key",
}


def ensure_connector_endpoint_tables() -> None:
    engine = get_engine()
    SQLModels.Base.metadata.create_all(
        bind=engine,
        tables=[SQLModels.ConnectorEndpoint.__table__],
        checkfirst=True,
    )


def list_connector_endpoint_rows(db, *, connector_key: str | None = None, enabled_only: bool = False):
    ensure_connector_endpoint_tables()
    query = db.query(SQLModels.ConnectorEndpoint).filter_by(is_deleted=False)
    if connector_key:
        query = query.filter_by(connector_key=connector_key)
    if enabled_only:
        query = query.filter_by(enabled=True)
    return query.order_by(SQLModels.ConnectorEndpoint.id.asc()).all()


def parse_json_text(raw_value: Any, *, default: Any) -> Any:
    if raw_value in (None, ""):
        return default
    if isinstance(raw_value, (dict, list)):
        return raw_value
    try:
        return json.loads(str(raw_value))
    except Exception:
        return default


def get_connector_endpoint_config(row) -> dict[str, Any]:
    loaded = parse_json_text(getattr(row, "config_json", None), default={})
    return loaded if isinstance(loaded, dict) else {}


def redact_connector_endpoint_config(config: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in dict(config or {}).items():
        if key in SECRET_CONFIG_KEYS:
            redacted[key] = MASKED_SECRET_VALUE if str(value or "").strip() else ""
        else:
            redacted[key] = value
    return redacted


def merge_connector_endpoint_secret_config(
    existing_config: dict[str, Any],
    incoming_config: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(existing_config or {})
    for key, value in dict(incoming_config or {}).items():
        if key in SECRET_CONFIG_KEYS and str(value or "").strip() in {"", MASKED_SECRET_VALUE}:
            continue
        merged[key] = value
    return merged


def get_connector_delivery_capabilities(row) -> list[str]:
    loaded = parse_json_text(getattr(row, "delivery_capabilities_json", None), default=[])
    if not isinstance(loaded, list):
        return []
    return [str(item).strip() for item in loaded if str(item).strip()]


def set_connector_endpoint_payload(
    row,
    *,
    connector_key: str,
    label: str | None,
    enabled: bool,
    config: dict[str, Any],
    delivery_capabilities: list[str] | None = None,
) -> None:
    row.connector_key = connector_key
    row.label = (label or "").strip() or None
    row.enabled = bool(enabled)
    row.config_json = json.dumps(config, sort_keys=True)
    row.delivery_capabilities_json = json.dumps(delivery_capabilities or [])
    row.is_deleted = False
    row.deleted_at = None
