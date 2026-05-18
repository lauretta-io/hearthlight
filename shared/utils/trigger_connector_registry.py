from __future__ import annotations

from .plugin_loader import load_plugin_catalog


def load_trigger_zoo() -> list[dict]:
    catalog = load_plugin_catalog()
    return [dict(entry) for entry in catalog.get("triggers", []) if entry.get("enabled", True)]


def load_connector_zoo() -> list[dict]:
    catalog = load_plugin_catalog()
    return [dict(entry) for entry in catalog.get("connectors", []) if entry.get("enabled", True)]


def load_rule_set_zoo() -> list[dict]:
    catalog = load_plugin_catalog()
    return [dict(entry) for entry in catalog.get("rule_sets", []) if entry.get("enabled", True)]
