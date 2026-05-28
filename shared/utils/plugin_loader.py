from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf

from .model_registry import (
    MODEL_STAGE_ANOMALY_STAGE_1,
    MODEL_STAGE_ANOMALY_STAGE_2,
    MODEL_STAGE_DETECTOR,
    MODEL_STAGE_REID,
    MODEL_STAGE_TRACKER,
    MODEL_ZOO_MASTER_CATALOG_SOURCE,
)

logger = logging.getLogger(__name__)

SHARED_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = SHARED_ROOT / "plugins"
PLUGIN_MANIFEST_FILENAME = "plugin.yaml"
COMPONENT_TYPE_MODEL = "model"
COMPONENT_TYPE_TRIGGER = "trigger"
COMPONENT_TYPE_CONNECTOR = "connector"
COMPONENT_TYPE_RULE_SET = "rule_set"
MODEL_STAGES = (
    MODEL_STAGE_DETECTOR,
    MODEL_STAGE_TRACKER,
    MODEL_STAGE_REID,
    MODEL_STAGE_ANOMALY_STAGE_1,
    MODEL_STAGE_ANOMALY_STAGE_2,
)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = OmegaConf.load(path)
    if raw is None:
        return {}
    loaded = OmegaConf.to_container(raw, resolve=True)
    return loaded if isinstance(loaded, dict) else {}


def _normalize_catalog_entry(key: str, value: Any) -> dict[str, Any]:
    entry = dict(value or {})
    entry["key"] = str(key)
    entry.setdefault("label", str(key).replace("_", " ").title())
    entry.setdefault("description", "")
    entry.setdefault("enabled", True)
    entry.setdefault("category", "general")
    entry.setdefault("requirements", [])
    entry.setdefault("fields", [])
    entry.setdefault("delivery_capabilities", [])
    return entry


def _fingerprint_path(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(str(path).encode("utf-8"))
    digest.update(b"\0")
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _resolve_component_path(plugin_dir: Path, value: str | None) -> Path | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    resolved = (plugin_dir / normalized).resolve()
    return resolved


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    loaded = _load_yaml(manifest_path)
    if not loaded:
        raise ValueError("manifest is empty")
    plugin_key = str(loaded.get("key") or "").strip()
    if not plugin_key:
        raise ValueError("plugin key is required")
    return {
        "key": plugin_key,
        "label": str(loaded.get("label") or plugin_key.replace("_", " ").title()).strip(),
        "version": str(loaded.get("version") or "0.0.0").strip(),
        "provider": str(loaded.get("provider") or "").strip() or None,
        "description": str(loaded.get("description") or "").strip(),
        "enabled_by_default": bool(loaded.get("enabled_by_default", True)),
        "components": dict(loaded.get("components") or {}),
        "manifest_path": str(manifest_path),
        "manifest_fingerprint": _fingerprint_path(manifest_path),
        "plugin_dir": str(manifest_path.parent),
    }


def _load_component_file(path: Path) -> dict[str, Any]:
    loaded = _load_yaml(path)
    if not isinstance(loaded, dict):
        return {}
    return loaded


def load_plugin_catalog(
    *,
    plugin_root: Path | None = None,
    upstream_model_catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = plugin_root or PLUGIN_ROOT
    catalog: dict[str, Any] = {
        "plugins": [],
        "models": {stage: {} for stage in MODEL_STAGES},
        "triggers": [],
        "connectors": [],
        "rule_sets": [],
        "components": [],
    }
    if not root.exists():
        return catalog

    for plugin_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        manifest_path = plugin_dir / PLUGIN_MANIFEST_FILENAME
        if not manifest_path.exists():
            continue
        plugin_key = plugin_dir.name
        try:
            plugin_entry = _load_manifest(manifest_path)
            plugin_key = plugin_entry["key"]
            plugin_entry.update(
                {
                    "load_status": "active",
                    "load_error": None,
                }
            )
            components = dict(plugin_entry.get("components") or {})

            if components.get("include_model_zoo") and isinstance(upstream_model_catalog, dict):
                upstream_models = upstream_model_catalog.get("models")
                if isinstance(upstream_models, dict):
                    for stage in MODEL_STAGES:
                        stage_models = dict(upstream_models.get(stage) or {})
                        for model_key, registration in stage_models.items():
                            normalized = dict(registration or {})
                            normalized.setdefault("stage", stage)
                            normalized.setdefault("adapter", model_key)
                            normalized.setdefault("plugin_key", plugin_key)
                            normalized.setdefault("source_path", MODEL_ZOO_MASTER_CATALOG_SOURCE)
                            catalog["models"][stage][model_key] = normalized
                            catalog["components"].append(
                                {
                                    "component_key": model_key,
                                    "component_type": COMPONENT_TYPE_MODEL,
                                    "plugin_key": plugin_key,
                                    "stage": stage,
                                    "category": "model",
                                    "source_path": MODEL_ZOO_MASTER_CATALOG_SOURCE,
                                    "metadata": {
                                        "adapter": normalized.get("adapter"),
                                        "artifact_ref": normalized.get("artifact_ref"),
                                        "runtime": normalized.get("runtime") or {},
                                        "capabilities": normalized.get("capabilities") or {},
                                    },
                                    "availability_status": "active",
                                    "load_error": None,
                                }
                            )

            model_files = dict(components.get("model_files") or {})
            for stage, relative_path in model_files.items():
                if stage not in MODEL_STAGES:
                    continue
                resolved_path = _resolve_component_path(manifest_path.parent, str(relative_path))
                if resolved_path is None or not resolved_path.exists():
                    raise ValueError(f"missing model file for stage {stage}: {relative_path}")
                loaded_models = _load_component_file(resolved_path)
                for model_key, registration in loaded_models.items():
                    normalized = dict(registration or {})
                    normalized.setdefault("stage", stage)
                    normalized.setdefault("adapter", model_key)
                    normalized["plugin_key"] = plugin_key
                    normalized["source_path"] = str(resolved_path)
                    catalog["models"][stage][model_key] = normalized
                    catalog["components"].append(
                        {
                            "component_key": model_key,
                            "component_type": COMPONENT_TYPE_MODEL,
                            "plugin_key": plugin_key,
                            "stage": stage,
                            "category": "model",
                            "source_path": str(resolved_path),
                            "metadata": {
                                "adapter": normalized.get("adapter"),
                                "artifact_ref": normalized.get("artifact_ref"),
                                "runtime": normalized.get("runtime") or {},
                                "capabilities": normalized.get("capabilities") or {},
                            },
                            "availability_status": "active",
                            "load_error": None,
                        }
                    )

            for component_type, file_key, catalog_key in (
                (COMPONENT_TYPE_TRIGGER, "trigger_file", "triggers"),
                (COMPONENT_TYPE_CONNECTOR, "connector_file", "connectors"),
                (COMPONENT_TYPE_RULE_SET, "rule_set_file", "rule_sets"),
            ):
                relative_path = components.get(file_key)
                resolved_path = _resolve_component_path(manifest_path.parent, relative_path)
                if resolved_path is None:
                    continue
                if not resolved_path.exists():
                    raise ValueError(f"missing {component_type} file: {relative_path}")
                loaded_entries = _load_component_file(resolved_path)
                for entry_key, value in sorted(loaded_entries.items()):
                    normalized = _normalize_catalog_entry(str(entry_key), value)
                    normalized["plugin_key"] = plugin_key
                    normalized["source_path"] = str(resolved_path)
                    catalog[catalog_key].append(normalized)
                    catalog["components"].append(
                        {
                            "component_key": normalized["key"],
                            "component_type": component_type,
                            "plugin_key": plugin_key,
                            "stage": None,
                            "category": str(normalized.get("category") or "general"),
                            "source_path": str(resolved_path),
                            "metadata": normalized,
                            "availability_status": "active",
                            "load_error": None,
                        }
                    )

        except Exception as exc:
            logger.exception("Failed to load plugin manifest from %s", manifest_path)
            plugin_entry = {
                "key": plugin_key,
                "label": plugin_key.replace("_", " ").title(),
                "version": "0.0.0",
                "provider": None,
                "description": "",
                "enabled_by_default": False,
                "components": {},
                "manifest_path": str(manifest_path),
                "manifest_fingerprint": _fingerprint_path(manifest_path) if manifest_path.exists() else None,
                "plugin_dir": str(plugin_dir),
                "load_status": "invalid",
                "load_error": str(exc),
            }

        catalog["plugins"].append(plugin_entry)

    catalog["plugins"].sort(key=lambda item: item["key"])
    catalog["triggers"].sort(key=lambda item: item["key"])
    catalog["connectors"].sort(key=lambda item: item["key"])
    catalog["rule_sets"].sort(key=lambda item: item["key"])
    catalog["components"].sort(key=lambda item: (item["component_type"], item["component_key"]))
    return catalog


def build_plugin_component_lookup(plugin_catalog: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    lookup: dict[str, dict[str, dict[str, Any]]] = {
        COMPONENT_TYPE_MODEL: {},
        COMPONENT_TYPE_TRIGGER: {},
        COMPONENT_TYPE_CONNECTOR: {},
        COMPONENT_TYPE_RULE_SET: {},
    }
    for component in plugin_catalog.get("components", []):
        component_type = str(component.get("component_type") or "").strip()
        component_key = str(component.get("component_key") or "").strip()
        if component_type in lookup and component_key:
            lookup[component_type][component_key] = component
    return lookup


def sync_plugin_catalog_to_db(db, plugin_catalog: dict[str, Any], sql_models) -> None:
    active_plugin_keys: set[str] = set()
    active_component_keys: set[tuple[str, str]] = set()
    existing_plugin_rows = {
        row.plugin_key: row
        for row in db.query(sql_models.PluginBundle).order_by(sql_models.PluginBundle.id.asc()).all()
    }
    existing_component_rows = {
        (row.component_type, row.component_key): row
        for row in db.query(sql_models.PluginComponent).order_by(sql_models.PluginComponent.id.asc()).all()
    }

    for plugin in plugin_catalog.get("plugins", []):
        plugin_key = str(plugin.get("key") or "").strip()
        if not plugin_key:
            continue
        active_plugin_keys.add(plugin_key)
        row = existing_plugin_rows.get(plugin_key)
        if row is None:
            row = sql_models.PluginBundle(plugin_key=plugin_key)
            db.add(row)
            existing_plugin_rows[plugin_key] = row
        row.label = plugin.get("label")
        row.version = plugin.get("version")
        row.provider = plugin.get("provider")
        row.description = plugin.get("description")
        row.enabled_by_default = bool(plugin.get("enabled_by_default", True))
        row.manifest_path = plugin.get("manifest_path")
        row.manifest_fingerprint = plugin.get("manifest_fingerprint")
        row.load_status = plugin.get("load_status") or "active"
        row.load_error = plugin.get("load_error")
        row.is_deleted = False
        row.deleted_at = None

    for component in plugin_catalog.get("components", []):
        component_type = str(component.get("component_type") or "").strip()
        component_key = str(component.get("component_key") or "").strip()
        plugin_key = str(component.get("plugin_key") or "").strip()
        if not component_type or not component_key or not plugin_key:
            continue
        if (component_type, component_key) in active_component_keys:
            continue
        active_component_keys.add((component_type, component_key))
        row = existing_component_rows.get((component_type, component_key))
        if row is None:
            row = sql_models.PluginComponent(
                component_type=component_type,
                component_key=component_key,
            )
            db.add(row)
            existing_component_rows[(component_type, component_key)] = row
        row.plugin_key = plugin_key
        row.stage = component.get("stage")
        row.category = component.get("category")
        row.source_path = component.get("source_path")
        row.metadata_json = json.dumps(component.get("metadata") or {}, sort_keys=True)
        row.availability_status = component.get("availability_status") or "active"
        row.load_error = component.get("load_error")
        row.is_deleted = False
        row.deleted_at = None

    for row in db.query(sql_models.PluginBundle).all():
        if row.plugin_key in active_plugin_keys:
            continue
        row.load_status = "missing"
        row.load_error = "plugin manifest is missing from disk"

    for row in db.query(sql_models.PluginComponent).all():
        key = (row.component_type, row.component_key)
        if key in active_component_keys:
            continue
        row.availability_status = "missing"
        row.load_error = "plugin component is missing from disk"
