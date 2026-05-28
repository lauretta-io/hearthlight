from __future__ import annotations

import json
import logging
import uuid
from threading import Thread
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from .connector_endpoints import (
    CONNECTOR_KEY_GOVEE,
    ensure_connector_endpoint_tables,
    get_connector_endpoint_config,
)

logger = logging.getLogger(__name__)

GOVEE_API_BASE_URL = "https://openapi.api.govee.com/router/api/v1"
GOVEE_TIMEOUT_SECONDS = 10.0
GOVEE_SUPPORTED_LIGHT_INSTANCES = {
    "powerSwitch",
    "brightness",
    "colorRgb",
    "colorTemperatureK",
    "lightScene",
    "diyScene",
    "snapshot",
    "nightlightScene",
    "presetScene",
}


def ensure_govee_connector_tables() -> None:
    ensure_connector_endpoint_tables()


def _govee_request(
    path: str,
    *,
    api_key: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = GOVEE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    normalized_key = str(api_key or "").strip()
    if not normalized_key:
        raise RuntimeError("Govee API key is required")
    data = None
    headers = {
        "Content-Type": "application/json",
        "Govee-API-Key": normalized_key,
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        f"{GOVEE_API_BASE_URL}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib_request.urlopen(req, timeout=timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Govee request failed: HTTP {exc.code} {detail}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"Govee request failed: {exc.reason}") from exc
    except Exception as exc:
        raise RuntimeError("Govee request failed") from exc

    code = int(body.get("code", 0) or 0)
    if code != 200:
        message = str(body.get("message") or body.get("msg") or "Govee rejected the request")
        raise RuntimeError(message)
    return body


def _build_enum_values(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        values.append(
            {
                "label": str(option.get("name") or option.get("value") or "option"),
                "value": option.get("value"),
            }
        )
    return values


def build_govee_capability_options(capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for capability in capabilities or []:
        if not isinstance(capability, dict):
            continue
        capability_type = str(capability.get("type") or "").strip()
        instance = str(capability.get("instance") or "").strip()
        if not capability_type or not instance:
            continue
        if instance not in GOVEE_SUPPORTED_LIGHT_INSTANCES and "scene" not in instance.lower():
            continue

        parameters = capability.get("parameters") or {}
        key = f"{capability_type}:{instance}"
        if capability_type == "devices.capabilities.on_off" and instance == "powerSwitch":
            options.append(
                {
                    "key": key,
                    "label": "Power",
                    "capability_type": capability_type,
                    "instance": instance,
                    "input_kind": "enum",
                    "values": _build_enum_values(list(parameters.get("options") or [])),
                    "default_value": 1,
                }
            )
            continue
        if capability_type == "devices.capabilities.range" and instance == "brightness":
            value_range = dict(parameters.get("range") or {})
            options.append(
                {
                    "key": key,
                    "label": "Brightness",
                    "capability_type": capability_type,
                    "instance": instance,
                    "input_kind": "integer",
                    "range": value_range,
                    "default_value": value_range.get("max", 100),
                }
            )
            continue
        if capability_type == "devices.capabilities.color_setting" and instance == "colorRgb":
            value_range = dict(parameters.get("range") or {})
            options.append(
                {
                    "key": key,
                    "label": "RGB Color",
                    "capability_type": capability_type,
                    "instance": instance,
                    "input_kind": "color",
                    "range": value_range,
                    "default_value": value_range.get("min", 0),
                }
            )
            continue
        if capability_type == "devices.capabilities.color_setting" and instance == "colorTemperatureK":
            value_range = dict(parameters.get("range") or {})
            options.append(
                {
                    "key": key,
                    "label": "Color Temperature",
                    "capability_type": capability_type,
                    "instance": instance,
                    "input_kind": "integer",
                    "range": value_range,
                    "default_value": value_range.get("min", 2000),
                }
            )
            continue
        if capability_type in {"devices.capabilities.dynamic_scene", "devices.capabilities.mode"} and "scene" in instance.lower():
            enum_values = _build_enum_values(list(parameters.get("options") or []))
            options.append(
                {
                    "key": key,
                    "label": "Scene",
                    "capability_type": capability_type,
                    "instance": instance,
                    "input_kind": "enum",
                    "values": enum_values,
                    "default_value": enum_values[0]["value"] if enum_values else None,
                }
            )
            continue
    return options


def discover_govee_devices(api_key: str) -> list[dict[str, Any]]:
    body = _govee_request("/user/devices", api_key=api_key, method="GET")
    devices = body.get("data") or []
    discovered: list[dict[str, Any]] = []
    for entry in devices:
        if not isinstance(entry, dict):
            continue
        capabilities = list(entry.get("capabilities") or [])
        capability_options = build_govee_capability_options(capabilities)
        if not capability_options:
            continue
        discovered.append(
            {
                "sku": str(entry.get("sku") or "").strip(),
                "device": str(entry.get("device") or "").strip(),
                "device_name": str(entry.get("deviceName") or entry.get("device_name") or entry.get("sku") or "").strip(),
                "device_type": str(entry.get("type") or "").strip() or None,
                "capability_options": capability_options,
            }
        )
    return discovered


def test_govee_api_key(api_key: str) -> dict[str, Any]:
    body = _govee_request("/user/devices", api_key=api_key, method="GET")
    raw_devices = list(body.get("data") or [])
    discovered = discover_govee_devices(api_key)
    return {
        "valid": True,
        "device_count": len(raw_devices),
        "light_device_count": len(discovered),
        "message": (
            "Govee API key is valid."
            if raw_devices
            else "Govee API key is valid, but no bound devices were returned for this account."
        ),
    }


def get_govee_device_state(*, api_key: str, sku: str, device: str) -> dict[str, Any]:
    body = _govee_request(
        "/device/state",
        api_key=api_key,
        method="POST",
        payload={
            "requestId": str(uuid.uuid4()),
            "payload": {
                "sku": str(sku or "").strip(),
                "device": str(device or "").strip(),
            },
        },
    )
    return dict(body.get("payload") or {})


def send_govee_device_control(
    *,
    api_key: str,
    sku: str,
    device: str,
    capability_type: str,
    instance: str,
    value: Any,
) -> dict[str, Any]:
    return _govee_request(
        "/device/control",
        api_key=api_key,
        method="POST",
        payload={
            "requestId": str(uuid.uuid4()),
            "payload": {
                "sku": str(sku or "").strip(),
                "device": str(device or "").strip(),
                "capability": {
                    "type": str(capability_type or "").strip(),
                    "instance": str(instance or "").strip(),
                    "value": value,
                },
            },
        },
    )


def _normalize_govee_row(row) -> dict[str, Any]:
    config = get_connector_endpoint_config(row)
    return {
        "label": str(getattr(row, "label", "") or "").strip(),
        "api_key": str(config.get("api_key", "") or "").strip(),
        "sku": str(config.get("sku", "") or "").strip(),
        "device": str(config.get("device", "") or "").strip(),
        "device_name": str(config.get("device_name", "") or "").strip(),
        "capability_type": str(config.get("capability_type", "") or "").strip(),
        "capability_instance": str(config.get("capability_instance", "") or "").strip(),
        "capability_value": config.get("capability_value"),
        "capability_value_label": str(config.get("capability_value_label", "") or "").strip(),
    }


def deliver_govee_trigger_actions(rows: list, *, trigger_text: str | None = None) -> list[str]:
    errors: list[str] = []
    for row in rows:
        normalized = _normalize_govee_row(row)
        if not normalized["api_key"] or not normalized["sku"] or not normalized["device"]:
            continue
        if not normalized["capability_type"] or not normalized["capability_instance"]:
            continue
        try:
            send_govee_device_control(
                api_key=normalized["api_key"],
                sku=normalized["sku"],
                device=normalized["device"],
                capability_type=normalized["capability_type"],
                instance=normalized["capability_instance"],
                value=normalized["capability_value"],
            )
        except Exception as exc:
            label = normalized["label"] or normalized["device_name"] or normalized["device"]
            message = f"{label}: {exc}"
            logger.warning("Failed to dispatch Govee trigger action: %s", message)
            errors.append(message)
    return errors


def queue_govee_trigger_actions(rows: list, *, trigger_text: str | None = None) -> None:
    if not rows:
        return

    def worker() -> None:
        try:
            deliver_govee_trigger_actions(rows, trigger_text=trigger_text)
        except Exception:
            logger.exception("Failed to dispatch Govee trigger actions")

    Thread(
        target=worker,
        daemon=True,
        name="govee-trigger-notifier",
    ).start()


def send_test_govee_trigger_action(row) -> None:
    normalized = _normalize_govee_row(row)
    send_govee_device_control(
        api_key=normalized["api_key"],
        sku=normalized["sku"],
        device=normalized["device"],
        capability_type=normalized["capability_type"],
        instance=normalized["capability_instance"],
        value=normalized["capability_value"],
    )
