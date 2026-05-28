import tempfile
import unittest
from pathlib import Path

from shared.utils.plugin_loader import (
    COMPONENT_TYPE_CONNECTOR,
    COMPONENT_TYPE_MODEL,
    COMPONENT_TYPE_RULE_SET,
    COMPONENT_TYPE_TRIGGER,
    load_plugin_catalog,
)


class PluginLoaderTests(unittest.TestCase):
    def test_core_plugin_loads_models_triggers_connectors_and_rule_sets(self):
        catalog = load_plugin_catalog()
        plugin_keys = {entry["key"] for entry in catalog["plugins"]}
        self.assertIn("core_builtin", plugin_keys)
        self.assertIn("govee_light_connection", plugin_keys)
        self.assertIn("builtin_yolox_s_cpu", catalog["models"]["detector"])
        self.assertIn("alert_rule_trigger", {entry["key"] for entry in catalog["triggers"]})
        self.assertIn("telegram", {entry["key"] for entry in catalog["connectors"]})
        self.assertIn("govee", {entry["key"] for entry in catalog["connectors"]})
        self.assertIn("starter_detection_rules", {entry["key"] for entry in catalog["rule_sets"]})

        connector_plugins = {
            entry["key"]: entry["plugin_key"]
            for entry in catalog["connectors"]
        }
        self.assertEqual(connector_plugins["govee"], "govee_light_connection")
        self.assertEqual(connector_plugins["telegram"], "core_builtin")

        component_types = {entry["component_type"] for entry in catalog["components"]}
        self.assertIn(COMPONENT_TYPE_MODEL, component_types)
        self.assertIn(COMPONENT_TYPE_TRIGGER, component_types)
        self.assertIn(COMPONENT_TYPE_CONNECTOR, component_types)
        self.assertIn(COMPONENT_TYPE_RULE_SET, component_types)

    def test_invalid_plugin_manifest_is_reported_without_crashing_catalog(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            plugin_dir = Path(temp_dir) / "broken_plugin"
            plugin_dir.mkdir(parents=True, exist_ok=True)
            (plugin_dir / "plugin.yaml").write_text("label: Broken Plugin\n", encoding="utf-8")

            catalog = load_plugin_catalog(plugin_root=Path(temp_dir))

        self.assertEqual(len(catalog["plugins"]), 1)
        plugin = catalog["plugins"][0]
        self.assertEqual(plugin["key"], "broken_plugin")
        self.assertEqual(plugin["load_status"], "invalid")
        self.assertTrue(plugin["load_error"])
        self.assertEqual(catalog["components"], [])


if __name__ == "__main__":
    unittest.main()
