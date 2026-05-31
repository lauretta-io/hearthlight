from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

import yaml

from .plugin_loader import PLUGIN_MANIFEST_FILENAME, PLUGIN_ROOT, load_plugin_catalog

DEFAULT_CONNECTOR_ZOO_CATALOG_URL = (
    str(os.environ.get("HEARTHLIGHT_CONNECTOR_ZOO_CATALOG_URL", "") or "").strip()
    or "https://raw.githubusercontent.com/lauretta-io/hearthlight/main/shared/catalogs/connector_zoo_repo.yaml"
)


def _read_url_bytes(url: str) -> bytes:
    request = urllib_request.Request(url, method="GET")
    try:
        with urllib_request.urlopen(request, timeout=10) as response:
            return response.read()
    except urllib_error.HTTPError as exc:
        raise RuntimeError(f"failed to fetch {url}: HTTP {exc.code}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"failed to fetch {url}: {exc.reason}") from exc


def _read_url_text(url: str) -> str:
    return _read_url_bytes(url).decode("utf-8")


def _resolve_catalog_reference(base_url: str, value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    parsed = urllib_parse.urlparse(normalized)
    if parsed.scheme:
        return normalized
    return urllib_parse.urljoin(base_url, normalized)


def _normalize_repo_connector_entry(value: Any) -> dict[str, Any]:
    entry = dict(value or {})
    key = str(entry.get("key") or "").strip().lower()
    if not key:
        raise ValueError("connector zoo entry key is required")
    plugin_key = str(entry.get("plugin_key") or "").strip()
    if not plugin_key:
        raise ValueError(f"connector zoo entry {key} requires plugin_key")
    normalized = {
        "key": key,
        "label": str(entry.get("label") or key.replace("_", " ").title()).strip(),
        "description": str(entry.get("description") or "").strip(),
        "category": str(entry.get("category") or "general").strip() or "general",
        "enabled": bool(entry.get("enabled", True)),
        "requirements": [str(item).strip() for item in list(entry.get("requirements") or []) if str(item).strip()],
        "fields": list(entry.get("fields") or []),
        "delivery_capabilities": [
            str(item).strip() for item in list(entry.get("delivery_capabilities") or []) if str(item).strip()
        ],
        "plugin_key": plugin_key,
        "plugin_version": str(entry.get("plugin_version") or "").strip() or None,
        "plugin_manifest_url": str(entry.get("plugin_manifest_url") or "").strip() or None,
        "plugin_bundle_url": str(entry.get("plugin_bundle_url") or "").strip() or None,
        "plugin_files": {
            str(path).strip(): str(url).strip()
            for path, url in dict(entry.get("plugin_files") or {}).items()
            if str(path).strip() and str(url).strip()
        },
        "source_url": str(entry.get("source_url") or "").strip() or None,
    }
    if not normalized["plugin_bundle_url"] and not normalized["plugin_manifest_url"]:
        raise ValueError(f"connector zoo entry {key} requires plugin_bundle_url or plugin_manifest_url")
    return normalized


def load_repo_connector_catalog_from_url(
    catalog_url: str | None,
    *,
    installed_plugin_keys: set[str] | None = None,
) -> dict[str, Any]:
    normalized_url = str(catalog_url or "").strip() or DEFAULT_CONNECTOR_ZOO_CATALOG_URL
    if not normalized_url:
        return {
            "catalog_url": None,
            "source_url": None,
            "generated_at": None,
            "last_refreshed_at": None,
            "error": "connector zoo catalog URL is not configured",
            "from_cache": False,
            "connectors": [],
        }
    loaded = yaml.safe_load(_read_url_text(normalized_url)) or {}
    if not isinstance(loaded, dict):
        raise RuntimeError("connector zoo catalog must be a YAML mapping")
    raw_connectors = loaded.get("connectors") or []
    if not isinstance(raw_connectors, list):
        raise RuntimeError("connector zoo catalog connectors must be a list")
    plugin_keys = installed_plugin_keys or set()
    connectors = []
    for item in raw_connectors:
        resolved_item = dict(item or {})
        resolved_item["plugin_manifest_url"] = _resolve_catalog_reference(
            normalized_url,
            resolved_item.get("plugin_manifest_url"),
        )
        resolved_item["plugin_bundle_url"] = _resolve_catalog_reference(
            normalized_url,
            resolved_item.get("plugin_bundle_url"),
        )
        resolved_item["source_url"] = _resolve_catalog_reference(
            normalized_url,
            resolved_item.get("source_url"),
        )
        resolved_item["plugin_files"] = {
            str(path).strip(): _resolve_catalog_reference(normalized_url, file_url)
            for path, file_url in dict(resolved_item.get("plugin_files") or {}).items()
            if str(path).strip() and _resolve_catalog_reference(normalized_url, file_url)
        }
        normalized = _normalize_repo_connector_entry(resolved_item)
        normalized["installed"] = normalized["plugin_key"] in plugin_keys
        connectors.append(normalized)
    connectors.sort(key=lambda entry: entry["label"].lower())
    return {
        "catalog_url": normalized_url,
        "source_url": _resolve_catalog_reference(normalized_url, loaded.get("source_url")) or normalized_url,
        "generated_at": str(loaded.get("generated_at") or "").strip() or None,
        "last_refreshed_at": None,
        "error": None,
        "from_cache": False,
        "connectors": connectors,
    }


def install_repo_connector_plugin(entry: dict[str, Any], *, plugin_root: Path | None = None) -> str:
    plugin_key = str(entry.get("plugin_key") or "").strip()
    if not plugin_key:
        raise RuntimeError("connector zoo entry is missing plugin_key")
    root = (plugin_root or PLUGIN_ROOT).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target_dir = root / plugin_key
    manifest_path = target_dir / PLUGIN_MANIFEST_FILENAME
    if manifest_path.exists():
        return plugin_key

    temp_root = Path(tempfile.mkdtemp(prefix="hearthlight-connector-plugin-"))
    try:
        staged_dir = temp_root / plugin_key
        staged_dir.mkdir(parents=True, exist_ok=True)
        bundle_url = str(entry.get("plugin_bundle_url") or "").strip()
        manifest_url = str(entry.get("plugin_manifest_url") or "").strip()
        plugin_files = dict(entry.get("plugin_files") or {})

        if bundle_url:
            bundle_path = temp_root / "bundle.zip"
            bundle_path.write_bytes(_read_url_bytes(bundle_url))
            with zipfile.ZipFile(bundle_path) as zip_file:
                zip_file.extractall(staged_dir)
        else:
            if not manifest_url:
                raise RuntimeError("connector zoo entry requires plugin_manifest_url when plugin_bundle_url is not provided")
            (staged_dir / PLUGIN_MANIFEST_FILENAME).write_bytes(_read_url_bytes(manifest_url))
            for relative_path, file_url in plugin_files.items():
                destination = (staged_dir / relative_path).resolve()
                if staged_dir.resolve() not in destination.parents and destination != staged_dir.resolve():
                    raise RuntimeError(f"invalid plugin file path {relative_path}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(_read_url_bytes(file_url))

        catalog = load_plugin_catalog(plugin_root=temp_root)
        loaded_plugin_keys = {str(plugin.get("key") or "").strip() for plugin in catalog.get("plugins", [])}
        if plugin_key not in loaded_plugin_keys:
            raise RuntimeError(f"installed plugin bundle did not expose expected plugin {plugin_key}")
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(staged_dir, target_dir)
        return plugin_key
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
