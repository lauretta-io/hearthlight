import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from src.webapp.routes import external_routes


class _QueryStub:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter_by(self, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _DBStub:
    def __init__(self, query_rows):
        self._query_rows = list(query_rows)

    def query(self, _model):
        return _QueryStub(self._query_rows)


class PluginApiResponseTests(unittest.TestCase):
    @patch.object(external_routes, "ensure_plugin_tables")
    def test_build_plugin_bundle_responses_returns_persisted_bundle_rows(self, _mock_tables):
        db = _DBStub(
            [
                SimpleNamespace(
                    plugin_key="core_builtin",
                    label="Hearthlight Core",
                    version="0.8.0",
                    provider="Lauretta",
                    description="Built-in plugin bundle",
                    enabled_by_default=True,
                    manifest_path="/tmp/plugin.yaml",
                    manifest_fingerprint="abc123",
                    load_status="active",
                    load_error=None,
                    is_deleted=False,
                )
            ]
        )

        responses = external_routes.build_plugin_bundle_responses(db)

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].plugin_key, "core_builtin")
        self.assertEqual(responses[0].load_status, "active")

    @patch.object(external_routes, "ensure_plugin_tables")
    def test_build_plugin_component_responses_filters_by_plugin_key(self, _mock_tables):
        db = _DBStub(
            [
                SimpleNamespace(
                    plugin_key="core_builtin",
                    component_key="alert_rule_trigger",
                    component_type="trigger",
                    stage=None,
                    category="general",
                    source_path="/tmp/triggers.yaml",
                    metadata_json=json.dumps({"label": "Alert Rule Trigger"}),
                    availability_status="active",
                    load_error=None,
                    is_deleted=False,
                )
            ]
        )

        responses = external_routes.build_plugin_component_responses(db, plugin_key="core_builtin")

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].component_key, "alert_rule_trigger")
        self.assertEqual(responses[0].component_type, "trigger")

    @patch.object(external_routes, "ensure_alert_rule_tables")
    @patch.object(external_routes, "ensure_plugin_tables")
    @patch.object(external_routes, "get_active_source_rows", return_value=[])
    @patch.object(external_routes, "get_registry_bundle", return_value={"plugin_catalog": {"components": []}})
    def test_build_trigger_rule_responses_marks_missing_trigger_component_unresolved(
        self,
        _mock_bundle,
        _mock_sources,
        _mock_plugin_tables,
        _mock_alert_tables,
    ):
        db = _DBStub(
            [
                SimpleNamespace(
                    id=3,
                    trigger_key="alert_rule_trigger",
                    source_template_id=7,
                    source_ids_json=json.dumps([7]),
                    enabled=True,
                    sort_order=0,
                    rule_label="People alert",
                    rule_kind="detector",
                    signal_family="detector",
                    anomaly_target_kind=None,
                    target_key="PERSON",
                    min_confidence=0.7,
                    anomaly_cutoff=None,
                    alert_level="high",
                    delivery_target_ids_json="[]",
                    metadata_json="{}",
                    created_at=datetime(2026, 5, 18, 12, 0, 0),
                    updated_at=datetime(2026, 5, 18, 12, 0, 0),
                    is_deleted=False,
                )
            ]
        )

        responses = external_routes.build_trigger_rule_responses(db)

        self.assertEqual(len(responses), 1)
        self.assertFalse(responses[0].resolved)
        self.assertIn("trigger plugin component alert_rule_trigger is unavailable", responses[0].unavailable_reason)

    @patch.object(external_routes, "get_connector_endpoint_rows")
    @patch.object(external_routes, "get_active_source_rows", return_value=[])
    @patch.object(external_routes, "get_registry_bundle", return_value={"plugin_catalog": {"components": []}})
    def test_build_connector_endpoint_responses_marks_missing_connector_component_unresolved(
        self,
        _mock_bundle,
        _mock_sources,
        mock_rows,
    ):
        mock_rows.return_value = [
            SimpleNamespace(
                id=9,
                connector_key="telegram",
                label="Ops",
                enabled=True,
                config_json=json.dumps({"bot_token": "secret", "chat_id": "123"}),
                delivery_capabilities_json=json.dumps(["message"]),
                created_at=datetime(2026, 5, 18, 12, 0, 0),
                updated_at=datetime(2026, 5, 18, 12, 0, 0),
                is_deleted=False,
            )
        ]

        responses = external_routes.build_connector_endpoint_responses(object())

        self.assertEqual(len(responses), 1)
        self.assertFalse(responses[0].resolved)
        self.assertIn("connector plugin component telegram is unavailable", responses[0].unavailable_reason)


if __name__ == "__main__":
    unittest.main()
