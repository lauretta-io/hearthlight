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
    CONNECTOR_KEY_CLAUDE_API,
    ensure_connector_endpoint_tables,
    get_connector_endpoint_config,
)

logger = logging.getLogger(__name__)


def ensure_claude_api_connector_tables() -> None:
    ensure_connector_endpoint_tables()


def build_claude_trigger_payload(
    *,
    trigger_id: str,
    trigger_type: str,
    trigger_text: str,
    display_title: str | None = None,
    run_identifier: str | None = None,
    source_label: str | None = None,
    camera_id: int | None = None,
    alert_level: str | None = None,
    occurred_at: str | None = None,
    metadata: dict | None = None,
) -> dict[str, Any]:
    return {
        "model": "hearthlight-trigger-router",
        "max_tokens": 256,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": trigger_text,
                    }
                ],
            }
        ],
        "metadata": {
            "source": "hearthlight",
            "trigger_id": trigger_id,
            "trigger_type": trigger_type,
            "display_title": display_title,
            "run_identifier": run_identifier,
            "source_label": source_label,
            "camera_id": camera_id,
            "alert_level": alert_level,
            "occurred_at": occurred_at,
            **dict(metadata or {}),
        },
        "hearthlight": {
            "trigger_id": trigger_id,
            "trigger_type": trigger_type,
            "display_title": display_title,
            "run_identifier": run_identifier,
            "source_label": source_label,
            "camera_id": camera_id,
            "alert_level": alert_level,
            "occurred_at": occurred_at,
            "metadata": dict(metadata or {}),
        },
    }


def _positive_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def validate_claude_api_config(config: dict[str, Any]) -> dict[str, Any]:
    base_url = str(config.get("base_url") or "").strip()
    if not base_url:
        raise ValueError("base_url is required")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    auth_token = str(config.get("auth_token") or config.get("secret") or "").strip()
    timeout_seconds = _positive_int(config.get("timeout_seconds"), 10, minimum=1, maximum=120)
    retry_count = _positive_int(config.get("retry_count"), 1, minimum=0, maximum=5)
    return {
        "base_url": base_url,
        "auth_token": auth_token,
        "timeout_seconds": timeout_seconds,
        "retry_count": retry_count,
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
    if parsed.username or parsed.password:
        userinfo = parsed.username or ""
        if parsed.password:
            userinfo = f"{userinfo}:{parsed.password}"
        fallback_netloc = f"{userinfo}@{fallback_netloc}"
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


def _build_request(url: str, body: bytes, headers: dict[str, str]):
    return urllib_request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )


def send_claude_api_payload(row, payload: dict[str, Any]) -> dict[str, Any]:
    config = validate_claude_api_config(get_connector_endpoint_config(row))
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Hearthlight/connector",
    }
    if config["auth_token"]:
        headers["Authorization"] = f"Bearer {config['auth_token']}"
    attempts = config["retry_count"] + 1
    last_error: Exception | None = None
    for url in _candidate_urls(config["base_url"]):
        for attempt in range(attempts):
            request = _build_request(url, body, headers)
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
    raise RuntimeError(f"claude api delivery failed: {last_error}") from last_error


def deliver_claude_api_trigger_notifications(rows, *, payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for row in rows:
        label = getattr(row, "label", None) or "Claude API"
        try:
            result = send_claude_api_payload(row, payload)
            record_connector_delivery_event(
                connector_key=CONNECTOR_KEY_CLAUDE_API,
                connector_label=label,
                status="sent",
                status_code=result.get("status_code"),
                trigger_id=payload.get("hearthlight", {}).get("trigger_id"),
                trigger_type=payload.get("hearthlight", {}).get("trigger_type"),
                message=f"{label} accepted trigger payload",
            )
        except Exception as exc:
            message = f"{label}: {exc}"
            errors.append(message)
            logger.warning("Failed to deliver Claude API trigger notification: %s", message)
            record_connector_delivery_event(
                connector_key=CONNECTOR_KEY_CLAUDE_API,
                connector_label=label,
                status="error",
                trigger_id=payload.get("hearthlight", {}).get("trigger_id"),
                trigger_type=payload.get("hearthlight", {}).get("trigger_type"),
                message=message,
            )
    return errors


def queue_claude_api_trigger_notifications(rows, *, payload: dict[str, Any]) -> None:
    def _send():
        try:
            deliver_claude_api_trigger_notifications(rows, payload=payload)
        except Exception:
            logger.exception("Failed to dispatch Claude API trigger notifications")

    threading.Thread(target=_send, daemon=True, name="claude-api-trigger-notifier").start()


def send_test_claude_api_trigger_message(endpoint) -> None:
    payload = build_claude_trigger_payload(
        trigger_id="TEST-TRIGGER",
        trigger_type="MANUAL",
        trigger_text="Hearthlight test trigger payload",
        display_title="Connector Test",
        alert_level="Low",
        metadata={"purpose": "claude api connector test"},
    )
    send_claude_api_payload(endpoint, payload)
