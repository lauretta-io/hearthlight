import tempfile
import unittest
from pathlib import Path

import yaml

from shared.utils.plugin_loader import load_plugin_catalog
from shared.utils.repo_connector_zoo import (
    install_repo_connector_plugin,
    load_repo_connector_catalog_from_url,
)


class RepoConnectorZooTests(unittest.TestCase):
    def test_load_repo_connector_catalog_resolves_relative_paths_against_catalog_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugin_dir = root / "plugins" / "govee_light_connection"
            plugin_dir.mkdir(parents=True, exist_ok=True)
            catalog_path = root / "catalogs" / "connector_zoo.yaml"
            catalog_path.parent.mkdir(parents=True, exist_ok=True)
            catalog_path.write_text(
                yaml.safe_dump(
                    {
                        "generated_at": "2026-05-27T00:00:00Z",
                        "source_url": "./connector_zoo.yaml",
                        "connectors": [
                            {
                                "key": "govee",
                                "label": "Govee Light Connection",
                                "plugin_key": "govee_light_connection",
                                "plugin_manifest_url": "../plugins/govee_light_connection/plugin.yaml",
                                "plugin_files": {
                                    "connectors.yaml": "../plugins/govee_light_connection/connectors.yaml",
                                },
                                "source_url": "../plugins/govee_light_connection/",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            catalog = load_repo_connector_catalog_from_url(catalog_path.as_uri())

        connector = catalog["connectors"][0]
        self.assertEqual(catalog["source_url"], catalog_path.as_uri())
        self.assertTrue(connector["plugin_manifest_url"].endswith("/plugins/govee_light_connection/plugin.yaml"))
        self.assertTrue(connector["plugin_files"]["connectors.yaml"].endswith("/plugins/govee_light_connection/connectors.yaml"))
        self.assertTrue(connector["source_url"].endswith("/plugins/govee_light_connection/"))

    def test_load_repo_connector_catalog_from_file_url_marks_installed_plugins(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            catalog_path = root / "connector_zoo.yaml"
            catalog_path.write_text(
                yaml.safe_dump(
                    {
                        "generated_at": "2026-05-27T00:00:00Z",
                        "connectors": [
                            {
                                "key": "govee",
                                "label": "Govee Light Connection",
                                "plugin_key": "govee_light_connection",
                                "plugin_manifest_url": "file:///tmp/plugin.yaml",
                                "plugin_files": {
                                    "connectors.yaml": "file:///tmp/connectors.yaml",
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            catalog = load_repo_connector_catalog_from_url(
                catalog_path.as_uri(),
                installed_plugin_keys={"govee_light_connection"},
            )

        self.assertEqual(catalog["catalog_url"], catalog_path.as_uri())
        self.assertEqual(len(catalog["connectors"]), 1)
        self.assertTrue(catalog["connectors"][0]["installed"])
        self.assertEqual(catalog["connectors"][0]["key"], "govee")

    def test_install_repo_connector_plugin_from_manifest_and_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            source.mkdir(parents=True, exist_ok=True)
            (source / "plugin.yaml").write_text(
                "\n".join(
                    [
                        "key: demo_connector",
                        "label: Demo Connector",
                        "version: '1.0.0'",
                        "provider: Demo",
                        "enabled_by_default: false",
                        "components:",
                        "  connector_file: connectors.yaml",
                    ]
                ),
                encoding="utf-8",
            )
            (source / "connectors.yaml").write_text(
                yaml.safe_dump(
                    {
                        "webhook": {
                            "label": "Webhook",
                            "description": "Demo webhook connector",
                            "category": "integrations",
                            "requirements": ["url"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            plugin_root = root / "plugins"
            entry = {
                "plugin_key": "demo_connector",
                "plugin_manifest_url": (source / "plugin.yaml").as_uri(),
                "plugin_files": {
                    "connectors.yaml": (source / "connectors.yaml").as_uri(),
                },
            }

            installed_key = install_repo_connector_plugin(entry, plugin_root=plugin_root)
            catalog = load_plugin_catalog(plugin_root=plugin_root)

        self.assertEqual(installed_key, "demo_connector")
        self.assertIn("demo_connector", {item["key"] for item in catalog["plugins"]})
        connector_keys = {item["key"] for item in catalog["connectors"]}
        self.assertIn("webhook", connector_keys)


if __name__ == "__main__":
    unittest.main()
