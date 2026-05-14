from __future__ import annotations

from pathlib import Path
from typing import Any

from omegaconf import OmegaConf

SHARED_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_DIR = SHARED_ROOT / "configs" / "registries"
TRIGGER_ZOO_PATH = REGISTRY_DIR / "triggers.yaml"
CONNECTOR_ZOO_PATH = REGISTRY_DIR / "connectors.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = OmegaConf.load(path)
    if raw is None:
        return {}
    loaded = OmegaConf.to_container(raw, resolve=True)
    return loaded if isinstance(loaded, dict) else {}


def _normalize_catalog(loaded: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for key, value in sorted(loaded.items()):
        entry = dict(value or {})
        entry["key"] = str(key)
        entry.setdefault("label", str(key).replace("_", " ").title())
        entry.setdefault("description", "")
        entry.setdefault("enabled", True)
        entry.setdefault("category", "general")
        entry.setdefault("requirements", [])
        entry.setdefault("fields", [])
        entry.setdefault("delivery_capabilities", [])
        entries.append(entry)
    return entries


def load_trigger_zoo() -> list[dict[str, Any]]:
    return _normalize_catalog(_load_yaml(TRIGGER_ZOO_PATH))


def load_connector_zoo() -> list[dict[str, Any]]:
    return _normalize_catalog(_load_yaml(CONNECTOR_ZOO_PATH))

