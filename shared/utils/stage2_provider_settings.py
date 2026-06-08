from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from ..database.database import get_engine
from ..models import SQLModels
from .connector_endpoints import MASKED_SECRET_VALUE
from .workspace_settings import get_workspace_setting_value

logger = logging.getLogger(__name__)

PROVIDER_KEY_OPENAI = "openai"
PROVIDER_KEY_LM_STUDIO = "lm_studio"
PROVIDER_KEY_LAURETTA = "lauretta"
PROVIDER_KEY_CLAUDE_COMPATIBLE = "claude_compatible"
STAGE2_PROVIDER_KEYS = {
    PROVIDER_KEY_OPENAI,
    PROVIDER_KEY_LM_STUDIO,
    PROVIDER_KEY_LAURETTA,
    PROVIDER_KEY_CLAUDE_COMPATIBLE,
}
STAGE2_PROVIDER_SECRET_KEY_ENV = "WEBAPP_SECRET_ENCRYPTION_KEY"
LEGACY_CLAUDE_COMPATIBLE_SETTING_KEY = "claude_anomaly_model"

PROVIDER_METADATA: dict[str, dict[str, Any]] = {
    PROVIDER_KEY_OPENAI: {
        "display_name": "OpenAI",
        "secret_field": "api_key",
        "auth_optional": False,
        "base_url": "https://api.openai.com/v1",
        "base_url_env": "OPENAI_BASE_URL",
        "model_name": "gpt-5.4-mini",
        "model_name_env": "OPENAI_MODEL_NAME",
        "secret_env": "OPENAI_API_KEY",
        "timeout_seconds": 30,
    },
    PROVIDER_KEY_LM_STUDIO: {
        "display_name": "LM Studio",
        "secret_field": "api_key",
        "auth_optional": True,
        "base_url": "http://localhost:1234/v1",
        "base_url_env": "LM_STUDIO_API_BASE_URL",
        "model_name": "local-model",
        "model_name_env": "LM_STUDIO_MODEL_NAME",
        "secret_env": "LM_STUDIO_API_KEY",
        "timeout_seconds": 30,
    },
    PROVIDER_KEY_LAURETTA: {
        "display_name": "Lauretta",
        "secret_field": "api_key",
        "auth_optional": False,
        "base_url": "",
        "base_url_env": "LAURETTA_API_BASE_URL",
        "model_name": "lauretta-anomaly-stage-2",
        "model_name_env": "LAURETTA_MODEL_NAME",
        "secret_env": "LAURETTA_API_KEY",
        "timeout_seconds": 30,
    },
    PROVIDER_KEY_CLAUDE_COMPATIBLE: {
        "display_name": "Claude-Compatible",
        "secret_field": "auth_token",
        "auth_optional": False,
        "base_url": "",
        "base_url_env": "CLAUDE_COMPATIBLE_BASE_URL",
        "model_name": "claude-compatible-anomaly",
        "model_name_env": "CLAUDE_COMPATIBLE_MODEL_NAME",
        "secret_env": "CLAUDE_COMPATIBLE_AUTH_TOKEN",
        "timeout_seconds": 30,
    },
}


class Stage2ProviderSettingsError(RuntimeError):
    pass


class Stage2ProviderSettingsKeyUnavailable(Stage2ProviderSettingsError):
    pass


class Stage2ProviderSettingsDecryptError(Stage2ProviderSettingsError):
    pass


def ensure_stage2_provider_setting_tables() -> None:
    engine = get_engine()
    SQLModels.Base.metadata.create_all(
        bind=engine,
        tables=[SQLModels.Stage2ProviderSetting.__table__],
        checkfirst=True,
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_provider_key(provider_key: str) -> str:
    normalized = str(provider_key or "").strip().lower()
    if normalized not in STAGE2_PROVIDER_KEYS:
        raise ValueError(f"unsupported provider_key {provider_key!r}")
    return normalized


def _positive_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)


def _build_fernet() -> Fernet:
    secret = str(os.environ.get(STAGE2_PROVIDER_SECRET_KEY_ENV) or "").strip()
    if not secret:
        raise Stage2ProviderSettingsKeyUnavailable(
            f"{STAGE2_PROVIDER_SECRET_KEY_ENV} is required to read or write saved Stage 2 provider secrets"
        )
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret_payload(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True).encode("utf-8")
    return _build_fernet().encrypt(normalized).decode("utf-8")


def decrypt_secret_payload(token: str | None) -> dict[str, Any]:
    raw = str(token or "").strip()
    if not raw:
        return {}
    try:
        decrypted = _build_fernet().decrypt(raw.encode("utf-8"))
    except InvalidToken as exc:
        raise Stage2ProviderSettingsDecryptError(
            "stored Stage 2 provider secret could not be decrypted"
        ) from exc
    loaded = json.loads(decrypted.decode("utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def parse_json_text(raw_value: Any, *, default: Any) -> Any:
    if raw_value in (None, ""):
        return deepcopy(default)
    if isinstance(raw_value, (dict, list)):
        return deepcopy(raw_value)
    try:
        loaded = json.loads(str(raw_value))
    except Exception:
        return deepcopy(default)
    return loaded if isinstance(loaded, type(default)) else loaded


def get_stage2_provider_row(db, provider_key: str):
    ensure_stage2_provider_setting_tables()
    normalized = _normalize_provider_key(provider_key)
    return (
        db.query(SQLModels.Stage2ProviderSetting)
        .filter_by(provider_key=normalized, is_deleted=False)
        .order_by(SQLModels.Stage2ProviderSetting.id.asc())
        .first()
    )


def list_stage2_provider_rows(db):
    ensure_stage2_provider_setting_tables()
    return (
        db.query(SQLModels.Stage2ProviderSetting)
        .filter_by(is_deleted=False)
        .order_by(SQLModels.Stage2ProviderSetting.provider_key.asc())
        .all()
    )


def _base_payload_for_provider(
    provider_key: str,
    *,
    runtime_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = _normalize_provider_key(provider_key)
    metadata = PROVIDER_METADATA[normalized]
    runtime_defaults = dict(runtime_defaults or {})
    return {
        "provider_key": normalized,
        "display_name": metadata["display_name"],
        "enabled": False,
        "base_url": str(runtime_defaults.get("base_url") or metadata["base_url"] or "").strip(),
        "model_name": str(runtime_defaults.get("model_name") or metadata["model_name"] or "").strip(),
        "timeout_seconds": _positive_int(
            runtime_defaults.get("timeout_seconds"),
            int(metadata["timeout_seconds"]),
            minimum=1,
            maximum=300,
        ),
        "auth_optional": bool(runtime_defaults.get("auth_optional", metadata["auth_optional"])),
        "api_key": "",
        "auth_token": "",
        "secret_present": False,
        "last_test_status": None,
        "last_test_message": None,
        "last_tested_at": None,
    }


def _legacy_claude_compatible_payload(db) -> dict[str, Any] | None:
    loaded = get_workspace_setting_value(
        db,
        LEGACY_CLAUDE_COMPATIBLE_SETTING_KEY,
        default={},
    )
    if not isinstance(loaded, dict):
        return None
    base_url = str(loaded.get("base_url") or "").strip()
    model_name = str(loaded.get("model_name") or "").strip()
    auth_token = str(loaded.get("auth_token") or loaded.get("secret") or "").strip()
    if not any([base_url, model_name, auth_token, loaded.get("enabled")]):
        return None
    return {
        "enabled": bool(loaded.get("enabled")),
        "base_url": base_url,
        "model_name": model_name,
        "timeout_seconds": _positive_int(loaded.get("timeout_seconds"), 10, minimum=1, maximum=300),
        "auth_optional": False,
        "auth_token": auth_token,
    }


def _env_payload_for_provider(
    provider_key: str,
    *,
    runtime_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = PROVIDER_METADATA[_normalize_provider_key(provider_key)]
    runtime_defaults = dict(runtime_defaults or {})
    base_url_env = str(runtime_defaults.get("base_url_env") or metadata["base_url_env"] or "").strip()
    model_name_env = str(runtime_defaults.get("model_name_env") or metadata["model_name_env"] or "").strip()
    secret_env = str(runtime_defaults.get("api_key_env") or runtime_defaults.get("secret_env") or metadata["secret_env"] or "").strip()
    payload = _base_payload_for_provider(provider_key, runtime_defaults=runtime_defaults)
    if base_url_env:
        payload["base_url"] = str(os.environ.get(base_url_env) or "").strip() or payload["base_url"]
    if model_name_env:
        payload["model_name"] = str(os.environ.get(model_name_env) or "").strip() or payload["model_name"]
    secret_field = metadata["secret_field"]
    if secret_env:
        payload[secret_field] = str(os.environ.get(secret_env) or "").strip()
        payload["secret_present"] = bool(payload[secret_field])
    return payload


def _normalize_provider_payload(
    provider_key: str,
    payload: dict[str, Any],
    *,
    require_secret_if_enabled: bool,
) -> dict[str, Any]:
    normalized = _base_payload_for_provider(provider_key)
    normalized.update(
        {
            "enabled": bool(payload.get("enabled", normalized["enabled"])),
            "base_url": str(payload.get("base_url") or "").strip(),
            "model_name": str(payload.get("model_name") or "").strip(),
            "timeout_seconds": _positive_int(
                payload.get("timeout_seconds"),
                normalized["timeout_seconds"],
                minimum=1,
                maximum=300,
            ),
            "auth_optional": bool(payload.get("auth_optional", normalized["auth_optional"])),
            "last_test_status": payload.get("last_test_status"),
            "last_test_message": payload.get("last_test_message"),
            "last_tested_at": payload.get("last_tested_at"),
        }
    )
    metadata = PROVIDER_METADATA[_normalize_provider_key(provider_key)]
    normalized["auth_optional"] = bool(metadata["auth_optional"])
    secret_field = metadata["secret_field"]
    normalized[secret_field] = str(payload.get(secret_field) or "").strip()
    alternate_secret_field = "auth_token" if secret_field == "api_key" else "api_key"
    normalized[alternate_secret_field] = ""
    normalized["secret_present"] = bool(normalized[secret_field])

    if normalized["base_url"] and not normalized["base_url"].startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    if normalized["enabled"] and not normalized["base_url"]:
        raise ValueError("base_url is required when the provider is enabled")
    if normalized["enabled"] and not normalized["model_name"]:
        raise ValueError("model_name is required when the provider is enabled")
    if (
        normalized["enabled"]
        and require_secret_if_enabled
        and not normalized["auth_optional"]
        and not normalized[secret_field]
    ):
        field_label = "api_key" if secret_field == "api_key" else "auth_token"
        raise ValueError(f"{field_label} is required when the provider is enabled")
    return normalized


def _config_payload_from_normalized(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(payload.get("enabled")),
        "base_url": str(payload.get("base_url") or "").strip(),
        "model_name": str(payload.get("model_name") or "").strip(),
        "timeout_seconds": _positive_int(payload.get("timeout_seconds"), 30, minimum=1, maximum=300),
        "auth_optional": bool(payload.get("auth_optional", False)),
        "last_test_status": payload.get("last_test_status"),
        "last_test_message": payload.get("last_test_message"),
        "last_tested_at": payload.get("last_tested_at"),
    }


def _secret_payload_from_normalized(provider_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    secret_field = PROVIDER_METADATA[_normalize_provider_key(provider_key)]["secret_field"]
    return {secret_field: str(payload.get(secret_field) or "").strip()}


def _merge_secret_value(provider_key: str, existing_secret: dict[str, Any], incoming_payload: dict[str, Any]) -> dict[str, Any]:
    secret_field = PROVIDER_METADATA[_normalize_provider_key(provider_key)]["secret_field"]
    incoming = str(incoming_payload.get(secret_field) or "").strip()
    merged = dict(existing_secret or {})
    if incoming == MASKED_SECRET_VALUE:
        return merged
    merged[secret_field] = incoming
    return merged


def merge_stage2_provider_settings_draft(
    provider_key: str,
    incoming_payload: dict[str, Any],
    *,
    existing_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = _normalize_provider_key(provider_key)
    existing_payload = dict(existing_payload or {})
    secret_field = PROVIDER_METADATA[normalized]["secret_field"]
    existing_secret = {secret_field: str(existing_payload.get(secret_field) or "").strip()}
    merged_secret = _merge_secret_value(normalized, existing_secret, incoming_payload)
    return _normalize_provider_payload(
        normalized,
        {**existing_payload, **incoming_payload, **merged_secret},
        require_secret_if_enabled=True,
    )


def _merge_saved_row(
    provider_key: str,
    payload: dict[str, Any],
    row,
) -> dict[str, Any]:
    config_payload = parse_json_text(getattr(row, "config_json", None), default={})
    if isinstance(config_payload, dict):
        payload.update(
            {
                "enabled": bool(config_payload.get("enabled", payload["enabled"])),
                "base_url": str(config_payload.get("base_url") or payload["base_url"]).strip(),
                "model_name": str(config_payload.get("model_name") or payload["model_name"]).strip(),
                "timeout_seconds": _positive_int(
                    config_payload.get("timeout_seconds"),
                    int(payload["timeout_seconds"]),
                    minimum=1,
                    maximum=300,
                ),
                "auth_optional": bool(config_payload.get("auth_optional", payload["auth_optional"])),
                "last_test_status": config_payload.get("last_test_status"),
                "last_test_message": config_payload.get("last_test_message"),
                "last_tested_at": config_payload.get("last_tested_at"),
            }
        )
    secret_field = PROVIDER_METADATA[_normalize_provider_key(provider_key)]["secret_field"]
    try:
        secret_payload = decrypt_secret_payload(getattr(row, "secret_json_encrypted", None))
    except Stage2ProviderSettingsKeyUnavailable:
        secret_payload = {}
    payload[secret_field] = str(secret_payload.get(secret_field) or "").strip()
    payload["secret_present"] = bool(payload[secret_field])
    return payload


def get_effective_stage2_provider_settings(
    db,
    provider_key: str,
    *,
    runtime_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = _normalize_provider_key(provider_key)
    payload = _env_payload_for_provider(normalized, runtime_defaults=runtime_defaults)
    row = get_stage2_provider_row(db, normalized)
    if row is not None:
        payload = _merge_saved_row(normalized, payload, row)
    elif normalized == PROVIDER_KEY_CLAUDE_COMPATIBLE:
        legacy_payload = _legacy_claude_compatible_payload(db)
        if legacy_payload is not None:
            payload.update(legacy_payload)
            payload["secret_present"] = bool(payload.get("auth_token"))
    return _normalize_provider_payload(
        normalized,
        payload,
        require_secret_if_enabled=False,
    )


def redact_stage2_provider_settings_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_provider_payload(
        payload.get("provider_key") or "",
        payload,
        require_secret_if_enabled=False,
    )
    secret_field = PROVIDER_METADATA[normalized["provider_key"]]["secret_field"]
    redacted = dict(normalized)
    redacted[secret_field] = MASKED_SECRET_VALUE if redacted[secret_field] else ""
    redacted["secret_present"] = bool(normalized[secret_field])
    return redacted


def list_stage2_provider_settings(db) -> list[dict[str, Any]]:
    rows = {row.provider_key: row for row in list_stage2_provider_rows(db)}
    results: list[dict[str, Any]] = []
    for provider_key in sorted(STAGE2_PROVIDER_KEYS):
        payload = get_effective_stage2_provider_settings(db, provider_key)
        if provider_key in rows:
            payload = _merge_saved_row(provider_key, payload, rows[provider_key])
        results.append(redact_stage2_provider_settings_payload(payload))
    return results


def write_stage2_provider_settings(db, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing_by_key = {row.provider_key: row for row in list_stage2_provider_rows(db)}
    saved_results: list[dict[str, Any]] = []
    for incoming in payloads:
        provider_key = _normalize_provider_key(incoming.get("provider_key") or "")
        row = existing_by_key.get(provider_key)
        existing_secret: dict[str, Any] = {}
        if row is not None:
            existing_secret = decrypt_secret_payload(getattr(row, "secret_json_encrypted", None))
        elif provider_key == PROVIDER_KEY_CLAUDE_COMPATIBLE:
            legacy_payload = _legacy_claude_compatible_payload(db)
            if isinstance(legacy_payload, dict):
                existing_secret = {
                    "auth_token": str(legacy_payload.get("auth_token") or "").strip(),
                }
        else:
            env_payload = _env_payload_for_provider(provider_key)
            secret_field = PROVIDER_METADATA[provider_key]["secret_field"]
            env_secret = str(env_payload.get(secret_field) or "").strip()
            if env_secret:
                existing_secret = {secret_field: env_secret}
        merged_secret = _merge_secret_value(provider_key, existing_secret, incoming)
        merged_payload = dict(incoming)
        merged_payload.update(merged_secret)
        if row is not None:
            config_payload = parse_json_text(getattr(row, "config_json", None), default={})
            if isinstance(config_payload, dict):
                for key in ("last_test_status", "last_test_message", "last_tested_at"):
                    if key not in merged_payload or merged_payload.get(key) is None:
                        merged_payload[key] = config_payload.get(key)
        normalized = _normalize_provider_payload(
            provider_key,
            merged_payload,
            require_secret_if_enabled=True,
        )
        if row is None:
            row = SQLModels.Stage2ProviderSetting(provider_key=provider_key)
            db.add(row)
            existing_by_key[provider_key] = row
        row.provider_key = provider_key
        row.config_json = json.dumps(_config_payload_from_normalized(normalized), sort_keys=True)
        secret_payload = _secret_payload_from_normalized(provider_key, normalized)
        has_secret = any(str(v or "").strip() for v in secret_payload.values())
        row.secret_json_encrypted = encrypt_secret_payload(secret_payload) if has_secret else None
        row.is_deleted = False
        row.deleted_at = None
        saved_results.append(redact_stage2_provider_settings_payload(normalized))
    db.flush()
    return saved_results


def record_stage2_provider_test_status(
    db,
    provider_key: str,
    *,
    status: str,
    message: str | None = None,
) -> None:
    row = get_stage2_provider_row(db, provider_key)
    if row is None:
        return
    config_payload = parse_json_text(getattr(row, "config_json", None), default={})
    if not isinstance(config_payload, dict):
        config_payload = {}
    config_payload["last_test_status"] = str(status or "").strip() or None
    config_payload["last_test_message"] = str(message or "").strip() or None
    config_payload["last_tested_at"] = utc_now_iso()
    row.config_json = json.dumps(config_payload, sort_keys=True)
    row.is_deleted = False
    row.deleted_at = None
    db.flush()


def build_runtime_stage2_provider_settings(
    db,
    provider_key: str,
    *,
    runtime_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = get_effective_stage2_provider_settings(
        db,
        provider_key,
        runtime_defaults=runtime_defaults,
    )
    return _normalize_provider_payload(
        provider_key,
        payload,
        require_secret_if_enabled=False,
    )
