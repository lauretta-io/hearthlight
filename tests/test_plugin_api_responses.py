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
        self.committed = False
        self.rolled_back = False
        self.added = []

    def query(self, _model):
        return _QueryStub(self._query_rows)

    def add(self, row):
        self.added.append(row)

    def flush(self):
        return None

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class PluginApiResponseTests(unittest.TestCase):
    @patch.object(external_routes, "ensure_plugin_tables")
    def test_build_plugin_bundle_responses_returns_persisted_bundle_rows(self, _mock_tables):
        db = _DBStub(
            [
                SimpleNamespace(
                    plugin_key="core_builtin",
                    label="Hearthlight Core",
                    version="0.8.2",
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

    @patch.object(external_routes, "build_mounted_model_stage_responses", return_value=[])
    @patch.object(external_routes, "persist_mounted_models")
    @patch.object(external_routes, "persist_model_bindings")
    @patch.object(external_routes, "publish_system_message")
    @patch.object(external_routes, "log_resource_event")
    @patch.object(external_routes, "sync_upload_lifecycle_states")
    @patch.object(external_routes, "get_registry_bundle")
    @patch.object(external_routes, "get_active_source_rows")
    @patch.object(external_routes, "refresh_runtime_status", side_effect=[external_routes.SystemStatus.RUNNING, external_routes.SystemStatus.RUNNING])
    def test_update_mounted_models_force_clears_bindings_and_stops_run(
        self,
        _mock_status,
        mock_sources,
        mock_bundle,
        mock_sync_uploads,
        _mock_log_resource_event,
        mock_publish_system_message,
        mock_persist_bindings,
        mock_persist_mounted,
        _mock_build_response,
    ):
        source_row = SimpleNamespace(
            id=4,
            detector_model_key=None,
            tracker_model_key=None,
            anomaly_stage_1_model_key=None,
            anomaly_stage_2_model_key="smolvlm_stage_2_cpu",
        )
        mock_sources.return_value = [source_row]
        mock_bundle.return_value = {
            "models": {
                "detector": {
                    "builtin_yolox_s_cpu": {"adapter": "yolox_detector", "stage": "detector"},
                },
                "tracker": {
                    "builtin_bytetrack": {"adapter": "bytetrack_tracker", "stage": "tracker"},
                },
                "anomaly_stage_1": {
                    "siglip_stage_1_cpu": {"adapter": "siglip_stage_1", "stage": "anomaly_stage_1"},
                },
                "anomaly_stage_2": {
                    "smolvlm_stage_2_cpu": {"adapter": "smolvlm_stage_2", "stage": "anomaly_stage_2"},
                },
            },
            "bindings": {
                "defaults": {
                    "detector": "builtin_yolox_s_cpu",
                    "tracker": "builtin_bytetrack",
                    "anomaly_stage_1": "siglip_stage_1_cpu",
                    "anomaly_stage_2": "smolvlm_stage_2_cpu",
                }
            },
            "mounted_models": {
                "detector": ["builtin_yolox_s_cpu"],
                "tracker": ["builtin_bytetrack"],
                "anomaly_stage_1": ["siglip_stage_1_cpu"],
                "anomaly_stage_2": ["smolvlm_stage_2_cpu"],
            },
        }
        db = _DBStub([])

        external_routes.update_mounted_models(
            stages=[
                external_routes.MountedModelStage(stage="detector", mounted_model_keys=[]),
                external_routes.MountedModelStage(stage="tracker", mounted_model_keys=["builtin_bytetrack"]),
                external_routes.MountedModelStage(stage="anomaly_stage_1", mounted_model_keys=[]),
                external_routes.MountedModelStage(stage="anomaly_stage_2", mounted_model_keys=[]),
            ],
            force=True,
            db=db,
        )

        mock_publish_system_message.assert_called_once()
        mock_sync_uploads.assert_called_once()
        mock_persist_mounted.assert_called_once()
        mock_persist_bindings.assert_called_once_with(
            {
                "detector": None,
                "tracker": "builtin_bytetrack",
                "reid": None,
                "anomaly_stage_1": None,
                "anomaly_stage_2": None,
            }
        )
        self.assertIsNone(source_row.anomaly_stage_2_model_key)
        self.assertTrue(db.committed)

    @patch.object(external_routes, "build_alert_rule_options_response")
    @patch.object(external_routes, "get_active_source_rows")
    @patch.object(external_routes, "get_registry_bundle")
    @patch.object(external_routes, "list_connector_endpoint_rows")
    @patch.object(external_routes, "ensure_alert_rule_tables")
    def test_replace_trigger_rules_rejects_unknown_connector_target(
        self,
        _mock_tables,
        mock_list_connector_rows,
        mock_bundle,
        mock_sources,
        mock_option_catalog,
    ):
        db = _DBStub([])
        mock_bundle.return_value = {
            "plugin_catalog": {
                "components": [
                    {"component_key": "alert_rule_trigger", "component_type": "trigger"},
                    {"component_key": "telegram", "component_type": "connector"},
                ]
            }
        }
        mock_sources.return_value = [SimpleNamespace(id=1, label="Gate 1")]
        mock_option_catalog.return_value = external_routes.AlertRuleOptionCatalog.model_validate(
            {
                "sources": [
                    {
                        "source_id": 1,
                        "source_label": "Gate 1",
                        "signal_options": [
                            {
                                "signal_family": "detector",
                                "options": [{"key": "PERSON", "label": "PERSON"}],
                                "unavailable_reason": None,
                            }
                        ],
                    }
                ]
            }
        )
        mock_list_connector_rows.return_value = []

        with self.assertRaises(external_routes.HTTPException) as exc_info:
            external_routes.replace_trigger_rules(
                db,
                [
                    external_routes.TriggerRule(
                        trigger_key="alert_rule_trigger",
                        source_ids=[1],
                        rule_kind="detector",
                        signal_family="detector",
                        target_key="PERSON",
                        min_confidence=0.5,
                        alert_level="medium",
                        delivery_target_ids=[41],
                    )
                ],
            )

        self.assertEqual(exc_info.exception.status_code, 404)
        self.assertIn("connector target 41 not found", str(exc_info.exception.detail))


class RegistryBundleSyncTests(unittest.TestCase):
    def setUp(self):
        external_routes._registry_db_sync_in_progress = False
        external_routes._last_registry_db_sync_at = 0.0

    @patch.object(external_routes, "sync_registry_bundle_to_db")
    @patch.object(external_routes, "sync_plugin_catalog_to_db")
    @patch.object(external_routes, "ensure_plugin_tables")
    @patch.object(
        external_routes,
        "load_registry_bundle",
        return_value={"mounted_models": {}, "plugin_catalog": {"components": []}},
    )
    def test_get_registry_bundle_force_sync_does_not_raise_unbound_local(
        self,
        _load_bundle,
        _ensure_tables,
        _sync_plugins,
        _sync_registry,
    ):
        db = _DBStub([])

        bundle = external_routes.get_registry_bundle(db, force_sync=True)

        self.assertIn("mounted_models", bundle)
        self.assertFalse(external_routes._registry_db_sync_in_progress)
        self.assertTrue(db.committed)
        _sync_registry.assert_called_once()
        _sync_plugins.assert_called_once()

    @patch.object(external_routes, "build_source_responses", return_value=[])
    @patch.object(external_routes, "get_active_source_rows", return_value=[])
    def test_load_settings_input_sources_returns_empty_without_snapshot_work(
        self,
        _rows,
        _responses,
    ):
        db = _DBStub([])
        result = external_routes.load_settings_input_sources(db)
        self.assertEqual(result, [])
        _responses.assert_not_called()


if __name__ == "__main__":
    unittest.main()
