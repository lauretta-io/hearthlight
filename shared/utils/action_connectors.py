from __future__ import annotations

import json
import logging
import threading
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from .connector_delivery_log import record_connector_delivery_event
from .connector_endpoints import (
    ACTION_CONNECTOR_KEYS,
    ensure_connector_endpoint_tables,
    get_connector_endpoint_config,
)

logger = logging.getLogger(__name__)


ACTION_CONNECTOR_LABELS = {
    "philips_hue": "Philips Hue",
    "music_api": "Music API",
    "robot_action": "Robot Action",
}


def ensure_action_connector_tables() -> None:
    ensure_connector_endpoint_tables()


def _positive_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def validate_action_connector_config(config: dict[str, Any]) -> dict[str, Any]:
    base_url = str(config.get("base_url") or "").strip()
    if not base_url:
        raise ValueError("base_url is required")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    action_type = str(config.get("action_type") or "robot_action").strip().lower()
    if action_type not in ACTION_CONNECTOR_KEYS:
        raise ValueError("action_type must be one of philips_hue, music_api, robot_action")
    command = str(config.get("command") or "trigger").strip()
    if not command:
        raise ValueError("command is required")
    parameters = config.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")
    return {
        "action_type": action_type,
        "base_url": base_url,
        "auth_token": str(config.get("auth_token") or config.get("secret") or "").strip(),
        "command": command,
        "target": str(config.get("target") or "").strip(),
        "parameters": dict(parameters),
        "timeout_seconds": _positive_int(config.get("timeout_seconds"), 10, minimum=1, maximum=120),
        "retry_count": _positive_int(config.get("retry_count"), 1, minimum=0, maximum=5),
    }


def build_action_trigger_payload(
    *,
    connector_key: str,
    command: str,
    target: str | None = None,
    parameters: dict | None = None,
    trigger_id: str,
    trigger_type: str,
    display_title: str | None = None,
    run_identifier: str | None = None,
    source_label: str | None = None,
    camera_id: int | None = None,
    alert_level: str | None = None,
    occurred_at: str | None = None,
    metadata: dict | None = None,
) -> dict[str, Any]:
    return {
        "schema": "hearthlight.action.v1",
        "source": "hearthlight",
        "action": {
            "type": connector_key,
            "command": command,
            "target": target,
            "parameters": dict(parameters or {}),
        },
        "trigger": {
            "id": trigger_id,
            "type": trigger_type,
            "display_title": display_title,
            "run_identifier": run_identifier,
            "source_label": source_label,
            "camera_id": camera_id,
            "alert_level": alert_level,
            "occurred_at": occurred_at,
            "metadata": dict(metadata or {}),
        },
    }


def _candidate_urls(base_url: str) -> list[str]:
    parsed = urllib_parse.urlparse(base_url)
    if parsed.hostname not in {"host.docker.internal", "localhost", "127.0.0.1"}:
        return [base_url]
    fallback_host = (
        "localhost"
        if parsed.hostname == "host.docker.internal"
        else "host.docker.internal"
    )
    fallback_netloc = fallback_host
    if parsed.port is not None:
        fallback_netloc = f"{fallback_netloc}:{parsed.port}"
    fallback_url = urllib_parse.urlunparse(
        (
            parsed.scheme,
            fallback_netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )
    return [base_url, fallback_url]


def send_action_connector_payload(row, payload: dict[str, Any]) -> dict[str, Any]:
    config = validate_action_connector_config(get_connector_endpoint_config(row))
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Hearthlight/action-connector",
    }
    if config["auth_token"]:
        headers["Authorization"] = f"Bearer {config['auth_token']}"
    attempts = config["retry_count"] + 1
    last_error: Exception | None = None
    for url in _candidate_urls(config["base_url"]):
        for attempt in range(attempts):
            request = urllib_request.Request(
                url,
                data=body,
                headers=headers,
                method="POST",
            )
            try:
                with urllib_request.urlopen(request, timeout=config["timeout_seconds"]) as response:
                    response_body = response.read(2048).decode("utf-8", errors="replace")
                    if response.status >= 400:
                        raise RuntimeError(f"HTTP {response.status} {response_body}")
                    return {"status_code": response.status, "body": response_body}
            except urllib_error.HTTPError as exc:
                detail = exc.read(2048).decode("utf-8", errors="replace")
                last_error = RuntimeError(f"{url}: HTTP {exc.code} {detail}".strip())
            except urllib_error.URLError as exc:
                last_error = RuntimeError(f"{url}: {getattr(exc, 'reason', exc)}")
            except Exception as exc:
                last_error = RuntimeError(f"{url}: {exc}")
            if attempt < attempts - 1:
                continue
    raise RuntimeError(f"action connector delivery failed: {last_error}") from last_error


def deliver_action_trigger_notifications(rows, *, payloads_by_id: dict[int, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for row in rows:
        label = getattr(row, "label", None) or ACTION_CONNECTOR_LABELS.get(getattr(row, "connector_key", ""), "Action Connector")
        payload = payloads_by_id.get(int(row.id))
        if payload is None:
            continue
        try:
            result = send_action_connector_payload(row, payload)
            record_connector_delivery_event(
                connector_key=getattr(row, "connector_key", "action_connector"),
                connector_label=label,
                status="sent",
                status_code=result.get("status_code"),
                trigger_id=payload.get("trigger", {}).get("id"),
                trigger_type=payload.get("trigger", {}).get("type"),
                message=f"{label} accepted action payload",
            )
        except Exception as exc:
            message = f"{label}: {exc}"
            errors.append(message)
            logger.warning("Failed to deliver action trigger notification: %s", message)
            record_connector_delivery_event(
                connector_key=getattr(row, "connector_key", "action_connector"),
                connector_label=label,
                status="error",
                trigger_id=payload.get("trigger", {}).get("id"),
                trigger_type=payload.get("trigger", {}).get("type"),
                message=message,
            )
    return errors


def queue_action_trigger_notifications(rows, *, payloads_by_id: dict[int, dict[str, Any]]) -> None:
    if not rows:
        return

    def _send():
        try:
            deliver_action_trigger_notifications(rows, payloads_by_id=payloads_by_id)
        except Exception:
            logger.exception("Failed to dispatch action trigger notifications")

    threading.Thread(target=_send, daemon=True, name="action-trigger-notifier").start()


def send_test_action_connector_message(endpoint) -> None:
    config = validate_action_connector_config(get_connector_endpoint_config(endpoint))
    payload = build_action_trigger_payload(
        connector_key=config["action_type"],
        command=config["command"],
        target=config["target"],
        parameters=config["parameters"],
        trigger_id="TEST-TRIGGER",
        trigger_type="manual_trigger",
        display_title="Action Connector Test",
        alert_level="Low",
        metadata={"purpose": "action connector test"},
    )
    send_action_connector_payload(endpoint, payload)
