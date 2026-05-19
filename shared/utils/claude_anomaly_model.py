from __future__ import annotations

import json
import logging
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from .connector_endpoints import MASKED_SECRET_VALUE

logger = logging.getLogger(__name__)

SETTING_KEY_CLAUDE_ANOMALY_MODEL = "claude_anomaly_model"
CLAUDE_ANOMALY_REQUEST_SCHEMA = "hearthlight.anomaly_request.v1"
CLAUDE_ANOMALY_RESPONSE_SCHEMA = "hearthlight.anomaly_response.v1"
DEFAULT_CLAUDE_ANOMALY_MODEL_NAME = "claude-compatible-anomaly"
DEFAULT_CLAUDE_ANOMALY_PROMPT = (
    "Evaluate the Hearthlight anomaly candidate. Return only JSON matching "
    "hearthlight.anomaly_response.v1 with promote, category, title, score, "
    "reasoning, visible_items, and visible_activities."
)


def _positive_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _score(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 0.0), 1.0)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


class _SafePromptFields(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _render_prompt_template(
    prompt_template: str,
    *,
    candidate: dict[str, Any],
    anomaly_object_list: list[str],
    anomaly_activity_list: list[str],
) -> str:
    fields = _SafePromptFields(
        {
            "frames_count": str(max(1, len(candidate.get("asset_references") or []))),
            "input_details": json.dumps(
                {
                    "event_id": candidate.get("event_id"),
                    "camera_id": candidate.get("camera_id"),
                    "frame_id": candidate.get("frame_id"),
                    "candidate_category": candidate.get("category"),
                    "candidate_score": candidate.get("score"),
                    "candidate_reasoning": candidate.get("reasoning"),
                    "visible_items": candidate.get("visible_items") or [],
                    "visible_activities": candidate.get("visible_activities") or [],
                    "asset_references": candidate.get("asset_references") or [],
                },
                sort_keys=True,
            ),
            "anomaly_object_list": ", ".join(anomaly_object_list),
            "anomaly_activity_list": ", ".join(anomaly_activity_list),
        }
    )
    try:
        return prompt_template.format_map(fields)
    except (KeyError, IndexError, ValueError):
        logger.warning("Failed to render Claude anomaly prompt template", exc_info=True)
        return prompt_template


def _bool_value(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    return default


def default_claude_anomaly_model_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "base_url": "",
        "auth_token": "",
        "model_name": DEFAULT_CLAUDE_ANOMALY_MODEL_NAME,
        "timeout_seconds": 10,
        "retry_count": 1,
        "prompt_template": DEFAULT_CLAUDE_ANOMALY_PROMPT,
    }


def validate_claude_anomaly_model_config(
    config: dict[str, Any],
    *,
    require_base_url: bool | None = None,
) -> dict[str, Any]:
    merged = {**default_claude_anomaly_model_config(), **dict(config or {})}
    enabled = bool(merged.get("enabled"))
    base_url = str(merged.get("base_url") or "").strip()
    if require_base_url is None:
        require_base_url = enabled
    if require_base_url and not base_url:
        raise ValueError("base_url is required")
    if base_url and not base_url.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    model_name = str(merged.get("model_name") or "").strip()
    if not model_name:
        raise ValueError("model_name is required")
    prompt_template = str(merged.get("prompt_template") or "").strip()
    if not prompt_template:
        prompt_template = DEFAULT_CLAUDE_ANOMALY_PROMPT
    return {
        "enabled": enabled,
        "base_url": base_url,
        "auth_token": str(merged.get("auth_token") or merged.get("secret") or "").strip(),
        "model_name": model_name,
        "timeout_seconds": _positive_int(
            merged.get("timeout_seconds"),
            10,
            minimum=1,
            maximum=120,
        ),
        "retry_count": _positive_int(merged.get("retry_count"), 1, minimum=0, maximum=5),
        "prompt_template": prompt_template,
    }


def redact_claude_anomaly_model_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = validate_claude_anomaly_model_config(config, require_base_url=False)
    normalized["auth_token"] = (
        MASKED_SECRET_VALUE if str(normalized.get("auth_token") or "").strip() else ""
    )
    return normalized


def merge_claude_anomaly_model_secret_config(
    existing_config: dict[str, Any],
    incoming_config: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(existing_config or {})
    for key, value in dict(incoming_config or {}).items():
        if key == "auth_token" and str(value or "").strip() in {"", MASKED_SECRET_VALUE}:
            continue
        merged[key] = value
    return merged


def build_claude_anomaly_request(
    *,
    config: dict[str, Any],
    event_id: str,
    run_id: str | None,
    source_id: int | None,
    camera_id: int | None,
    frame_id: int | None,
    stage_1_model_key: str | None,
    stage_2_model_key: str | None,
    candidate_category: str,
    candidate_score: float,
    candidate_reasoning: str | None,
    visible_items: list[str],
    visible_activities: list[str],
    prompt_template: str | None = None,
    anomaly_object_list: list[str] | None = None,
    anomaly_activity_list: list[str] | None = None,
    asset_references: list[Any] | None = None,
) -> dict[str, Any]:
    normalized = validate_claude_anomaly_model_config(config, require_base_url=False)
    prompt_text = prompt_template or normalized["prompt_template"]
    assets = []
    for asset in asset_references or []:
        if hasattr(asset, "model_dump"):
            assets.append(asset.model_dump(mode="json"))
        elif isinstance(asset, dict):
            assets.append(dict(asset))
    candidate = {
        "event_id": event_id,
        "run_id": run_id,
        "source_id": source_id,
        "camera_id": camera_id,
        "frame_id": frame_id,
        "stage_1_model_key": stage_1_model_key,
        "stage_2_model_key": stage_2_model_key,
        "category": candidate_category,
        "score": _score(candidate_score),
        "reasoning": candidate_reasoning,
        "visible_items": list(visible_items or []),
        "visible_activities": list(visible_activities or []),
        "asset_references": assets,
    }
    anomaly_objects = list(anomaly_object_list or [])
    anomaly_activities = list(anomaly_activity_list or [])
    rendered_prompt = _render_prompt_template(
        prompt_text,
        candidate=candidate,
        anomaly_object_list=anomaly_objects,
        anomaly_activity_list=anomaly_activities,
    )
    hearthlight = {
        "schema": CLAUDE_ANOMALY_REQUEST_SCHEMA,
        "source": "hearthlight",
        "candidate": candidate,
        "prompt": {
            "template": rendered_prompt,
            "anomaly_object_list": anomaly_objects,
            "anomaly_activity_list": anomaly_activities,
        },
    }
    return {
        "model": normalized["model_name"],
        "max_tokens": 512,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"{rendered_prompt}\n\n"
                            "Candidate context JSON:\n"
                            f"{json.dumps(hearthlight, sort_keys=True)}"
                        ),
                    }
                ],
            }
        ],
        "metadata": {
            "source": "hearthlight",
            "purpose": "anomaly_detection",
            "schema": CLAUDE_ANOMALY_REQUEST_SCHEMA,
            "event_id": event_id,
            "source_id": source_id,
            "camera_id": camera_id,
            "frame_id": frame_id,
            "candidate_category": candidate_category,
        },
        "hearthlight": hearthlight,
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


def _extract_json_from_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty anomaly response")
    try:
        loaded = json.loads(stripped)
        if isinstance(loaded, dict):
            return loaded
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        loaded = json.loads(stripped[start : end + 1])
        if isinstance(loaded, dict):
            return loaded
    raise ValueError("Claude anomaly response did not contain a JSON object")


def extract_claude_anomaly_response_payload(response_payload: Any) -> dict[str, Any]:
    if isinstance(response_payload, str):
        return _extract_json_from_text(response_payload)
    if not isinstance(response_payload, dict):
        raise ValueError("Claude anomaly response must be a JSON object")
    for key in ("hearthlight", "anomaly", "result"):
        nested = response_payload.get(key)
        if isinstance(nested, dict) and (
            "promote" in nested or "category" in nested or "title" in nested
        ):
            return nested
    content = response_payload.get("content")
    if isinstance(content, list):
        text_parts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type", "text") == "text"
        ]
        if text_parts:
            return _extract_json_from_text("\n".join(text_parts))
    if isinstance(content, str):
        return _extract_json_from_text(content)
    result_keys = {
        "promote",
        "anomaly_detected",
        "is_anomaly",
        "should_alert",
        "category",
        "anomaly_category",
        "title",
        "confidence",
        "score",
    }
    if any(key in response_payload for key in result_keys):
        return response_payload
    raise ValueError("Claude anomaly response did not include anomaly result fields")


def parse_claude_anomaly_response(response_payload: Any) -> dict[str, Any]:
    payload = extract_claude_anomaly_response_payload(response_payload)
    score = _score(
        payload.get("score", payload.get("confidence", payload.get("anomaly_score", 0.0)))
    )
    promote_raw = payload.get(
        "promote",
        payload.get(
            "anomaly_detected",
            payload.get("is_anomaly", payload.get("should_alert")),
        ),
    )
    promote = _bool_value(promote_raw, default=score > 0.5)
    category = str(payload.get("category") or payload.get("anomaly_category") or "external_anomaly").strip()
    title = str(payload.get("title") or payload.get("display_title") or category).strip()
    reasoning = payload.get("reasoning", payload.get("rationale", payload.get("summary")))
    return {
        "schema": str(payload.get("schema") or CLAUDE_ANOMALY_RESPONSE_SCHEMA),
        "promote": promote,
        "category": category or "external_anomaly",
        "title": title or category or "External anomaly",
        "score": score,
        "reasoning": str(reasoning).strip() if reasoning is not None else None,
        "visible_items": _string_list(payload.get("visible_items", payload.get("items"))),
        "visible_activities": _string_list(
            payload.get("visible_activities", payload.get("activities"))
        ),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    }


def send_claude_anomaly_request(
    config: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = validate_claude_anomaly_model_config(config, require_base_url=True)
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Hearthlight/anomaly-model",
    }
    if normalized["auth_token"]:
        headers["Authorization"] = f"Bearer {normalized['auth_token']}"
    attempts = normalized["retry_count"] + 1
    last_error: Exception | None = None
    for url in _candidate_urls(normalized["base_url"]):
        for attempt in range(attempts):
            request = urllib_request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib_request.urlopen(
                    request,
                    timeout=normalized["timeout_seconds"],
                ) as response:
                    response_body = response.read(65536).decode("utf-8", errors="replace")
                    if response.status >= 400:
                        raise RuntimeError(f"HTTP {response.status} {response_body}")
                    loaded = json.loads(response_body) if response_body.strip() else {}
                    return parse_claude_anomaly_response(loaded)
            except urllib_error.HTTPError as exc:
                detail = exc.read(4096).decode("utf-8", errors="replace")
                last_error = RuntimeError(f"{url}: HTTP {exc.code} {detail}".strip())
            except urllib_error.URLError as exc:
                last_error = RuntimeError(f"{url}: {getattr(exc, 'reason', exc)}")
            except json.JSONDecodeError as exc:
                last_error = RuntimeError(f"{url}: invalid JSON response: {exc}")
            except Exception as exc:
                last_error = RuntimeError(f"{url}: {exc}")
            if attempt < attempts - 1:
                continue
    raise RuntimeError(f"claude anomaly model request failed: {last_error}") from last_error
