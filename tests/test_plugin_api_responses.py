import json
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

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


class _ExecuteResultStub:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class _ColumnEnsureDBStub:
    def __init__(self, rows):
        self._rows = list(rows)
        self.execute_calls = 0
        self.commit_calls = 0

    def execute(self, _query):
        self.execute_calls += 1
        return _ExecuteResultStub(self._rows)

    def commit(self):
        self.commit_calls += 1


class PluginApiResponseTests(unittest.TestCase):
    def setUp(self):
        external_routes.source_template_columns_ready = False
        external_routes.plugin_tables_ready = False
        external_routes.last_registry_bundle_sync_signature = None
        external_routes.dependency_status_cache = None

    def tearDown(self):
        external_routes.dependency_status_cache = None

    @patch.object(external_routes, "check_ffmpeg_dependency")
    @patch.object(external_routes, "check_rabbitmq_dependency")
    @patch.object(external_routes, "check_database_dependency")
    def test_dependency_status_is_cached_for_polling_bursts(
        self,
        mock_database,
        mock_rabbitmq,
        mock_ffmpeg,
    ):
        first = external_routes.collect_dependency_status()
        second = external_routes.collect_dependency_status()

        self.assertEqual(first, second)
        self.assertEqual(mock_database.call_count, 1)
        self.assertEqual(mock_rabbitmq.call_count, 1)
        self.assertEqual(mock_ffmpeg.call_count, 1)
        self.assertEqual(first["rabbitmq"]["status"], "ok")

    @patch.object(external_routes, "check_ffmpeg_dependency")
    @patch.object(external_routes, "check_rabbitmq_dependency")
    @patch.object(external_routes, "check_database_dependency")
    def test_dependency_status_cache_serializes_concurrent_misses(
        self,
        mock_database,
        mock_rabbitmq,
        mock_ffmpeg,
    ):
        def slow_rabbitmq_probe():
            time.sleep(0.05)

        mock_rabbitmq.side_effect = slow_rabbitmq_probe

        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(lambda _index: external_routes.collect_dependency_status(), range(6)))

        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(mock_database.call_count, 1)
        self.assertEqual(mock_rabbitmq.call_count, 1)
        self.assertEqual(mock_ffmpeg.call_count, 1)
        self.assertEqual(results[0]["rabbitmq"]["status"], "ok")

    @patch.object(external_routes, "get_current_resource_snapshot", return_value={"gpus": [{"name": "NVIDIA T4"}]})
    @patch.object(external_routes, "shutil")
    @patch.object(external_routes, "subprocess")
    def test_admin_media_smoke_reports_gpu_path(self, mock_subprocess, mock_shutil, _mock_snapshot):
        mock_shutil.which.side_effect = lambda binary: f"/usr/bin/{binary}"
        mock_subprocess.run.side_effect = [
            SimpleNamespace(returncode=0, stdout="GPU 0: NVIDIA T4\n", stderr=""),
            SimpleNamespace(returncode=0, stdout="Hardware acceleration methods:\ncuda\n", stderr=""),
        ]

        response = external_routes.post_admin_diagnostics_media_smoke(db=object())

        self.assertTrue(response["ok"])
        self.assertTrue(response["gpu_used"])
        self.assertTrue(response["cuda_video_path_available"])

    @patch.object(external_routes, "get_current_resource_snapshot", return_value={"gpus": []})
    @patch.object(external_routes, "shutil")
    @patch.object(external_routes, "subprocess")
    def test_admin_media_smoke_fails_closed_without_nvidia(self, mock_subprocess, mock_shutil, _mock_snapshot):
        mock_shutil.which.side_effect = lambda binary: "/usr/bin/ffmpeg" if binary == "ffmpeg" else None
        mock_subprocess.run.return_value = SimpleNamespace(
            returncode=0,
            stdout="Hardware acceleration methods:\nvideotoolbox\n",
            stderr="",
        )

        response = external_routes.post_admin_diagnostics_media_smoke(db=object())

        self.assertTrue(response["ok"])
        self.assertFalse(response["gpu_used"])

    @patch.object(external_routes, "_build_anomaly_llm_model_provider_test_result")
    @patch.object(external_routes, "select_anomaly_llm_model_provider_for_smoke")
    def test_admin_provider_smoke_reuses_anomaly_llm_model_provider_test(self, mock_select, mock_test):
        mock_select.return_value = {
            "provider_key": "openai",
            "display_name": "OpenAI",
            "enabled": True,
            "base_url": "https://api.openai.com/v1",
            "model_name": "gpt-5.4-mini",
            "timeout_seconds": 30,
            "auth_optional": False,
            "api_key": "secret",
            "auth_token": "",
            "secret_present": True,
        }
        mock_test.return_value = SimpleNamespace(
            provider_key="openai",
            ok=True,
            detail="Connection test succeeded.",
            effective_base_url="https://api.openai.com/v1",
            effective_model_name="gpt-5.4-mini",
            secret_present=True,
            request_reached_provider=True,
            normalized_result_returned=True,
            provider_response_validated=True,
            provider_response_shape="openai_chat_completions",
            last_test_status="ok",
            last_tested_at="2026-06-15T00:00:00Z",
        )

        response = external_routes.post_admin_diagnostics_provider_smoke(
            {"provider_key": "openai"},
            db=object(),
        )

        self.assertTrue(response["ok"])
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["provider_key"], "openai")
        self.assertTrue(response["request_reached_provider"])
        self.assertTrue(response["normalized_result_returned"])
        self.assertTrue(response["provider_response_validated"])
        self.assertEqual(response["provider_response_shape"], "openai_chat_completions")
        mock_select.assert_called_once()
        mock_test.assert_called_once()

    def test_provider_smoke_response_validators_require_provider_shapes(self):
        openai_result = external_routes.validate_openai_compatible_smoke_response(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "title": "Person returned",
                                    "category": "presence_resume",
                                    "score": 0.8,
                                    "reasoning": "A person re-entered the scene.",
                                }
                            )
                        }
                    }
                ]
            }
        )
        self.assertEqual(openai_result["category"], "presence_resume")
        with self.assertRaises(ValueError):
            external_routes.validate_openai_compatible_smoke_response({"id": "chatcmpl_missing_choices"})

        claude_result = external_routes.validate_claude_compatible_smoke_response(
            {
                "title": "Presence resume",
                "category": "presence_resume",
                "score": 0.7,
                "reasoning": "A person and bag are visible.",
            }
        )
        self.assertEqual(claude_result["category"], "presence_resume")

        lauretta_result = external_routes.validate_lauretta_smoke_response(
            {
                "submission_id": "sub_test",
                "status": "completed",
                "processed_bucket": "640x480",
            }
        )
        self.assertEqual(lauretta_result["submission_id"], "sub_test")
        with self.assertRaises(ValueError):
            external_routes.validate_lauretta_smoke_response({"status": "completed"})

    def test_runtime_profile_diagnostics_redacts_object_store_credentials(self):
        with patch.dict(
            "os.environ",
            {
                "API_WEB_CONCURRENCY": "12",
                "API_CLIENT_CACHE_TTL_SECONDS": "15",
                "HEARTHLIGHT_LOCAL_STACK": "false",
                "POSTGRES_HOST": "pgbouncer",
                "POSTGRES_PORT": "6432",
                "DB_POOL_SIZE": "4",
                "DB_MAX_OVERFLOW": "4",
                "HEARTHLIGHT_WORKER_RUNTIME": "docker",
                "WORKER_CONCURRENCY": "32",
                "WORKER_POLL_SECONDS": "0.05",
                "INLINE_INFERENCE_AFTER_PREPROCESS": "true",
                "HEARTHLIGHT_OBJECT_STORE_BACKEND": "s3",
                "HEARTHLIGHT_OBJECT_STORE_S3_BUCKET": "hearthlight-assets",
                "HEARTHLIGHT_OBJECT_STORE_S3_ENDPOINT_URL": "http://minio:9000",
                "HEARTHLIGHT_OBJECT_STORE_S3_ACCESS_KEY_ID": "minio",
                "HEARTHLIGHT_OBJECT_STORE_S3_SECRET_ACCESS_KEY": "super-secret",
            },
            clear=True,
        ):
            profile = external_routes._runtime_profile_diagnostics()

        self.assertEqual(profile["database"]["postgres_host"], "pgbouncer")
        self.assertEqual(profile["worker"]["worker_concurrency"], "32")
        self.assertEqual(profile["object_store"]["backend"], "s3")
        self.assertTrue(profile["object_store"]["s3_access_key_present"])
        self.assertTrue(profile["object_store"]["s3_secret_key_present"])
        self.assertNotIn("super-secret", json.dumps(profile))
        self.assertNotIn("HEARTHLIGHT_OBJECT_STORE_S3_SECRET_ACCESS_KEY", json.dumps(profile))

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

    def test_ensure_source_template_columns_only_hits_database_once_per_process(self):
        db = _ColumnEnsureDBStub(
            [
                ("frame_processing_mode",),
                ("process_every_n_frames",),
                ("target_frame_rate",),
            ]
        )

        external_routes.ensure_source_template_columns(db)
        external_routes.ensure_source_template_columns(db)

        self.assertEqual(db.execute_calls, 1)
        self.assertEqual(db.commit_calls, 0)

    @patch.object(external_routes, "sync_registry_bundle_to_db")
    @patch.object(external_routes, "sync_plugin_catalog_to_db")
    @patch.object(external_routes, "ensure_plugin_tables")
    @patch.object(external_routes, "load_registry_bundle")
    def test_get_registry_bundle_skips_duplicate_db_sync_when_inputs_unchanged(
        self,
        mock_load_registry_bundle,
        _mock_ensure_plugin_tables,
        mock_sync_plugin_catalog,
        mock_sync_registry_bundle,
    ):
        bundle = {
            "plugin_catalog": {"plugins": [], "components": []},
            "models": {},
            "mounted_models": {},
            "bindings": {},
        }
        mock_load_registry_bundle.return_value = bundle
        db = Mock()
        source_rows = [
            SimpleNamespace(
                id=7,
                updated_at=datetime(2026, 6, 4, 10, 0, 0),
                detector_model_key="builtin_yolox_s_cpu",
                tracker_model_key="builtin_bytetrack",
                anomaly_stage_1_model_key="siglip_stage_1_cpu",
                anomaly_stage_2_model_key="smolvlm_stage_2_cpu",
                is_deleted=False,
            )
        ]

        external_routes.get_registry_bundle(db, source_rows=source_rows)
        external_routes.get_registry_bundle(db, source_rows=source_rows)

        self.assertEqual(mock_sync_plugin_catalog.call_count, 1)
        self.assertEqual(mock_sync_registry_bundle.call_count, 1)
        db.commit.assert_called_once()

    @patch.object(external_routes, "sync_registry_bundle_to_db")
    @patch.object(external_routes, "sync_plugin_catalog_to_db")
    @patch.object(external_routes, "ensure_plugin_tables")
    @patch.object(external_routes, "load_registry_bundle")
    def test_get_registry_bundle_re_syncs_when_source_binding_signature_changes(
        self,
        mock_load_registry_bundle,
        _mock_ensure_plugin_tables,
        mock_sync_plugin_catalog,
        mock_sync_registry_bundle,
    ):
        bundle = {
            "plugin_catalog": {"plugins": [], "components": []},
            "models": {},
            "mounted_models": {},
            "bindings": {},
        }
        mock_load_registry_bundle.return_value = bundle
        db = Mock()
        first_sources = [
            SimpleNamespace(
                id=7,
                updated_at=datetime(2026, 6, 4, 10, 0, 0),
                detector_model_key="builtin_yolox_s_cpu",
                tracker_model_key="builtin_bytetrack",
                anomaly_stage_1_model_key="siglip_stage_1_cpu",
                anomaly_stage_2_model_key="smolvlm_stage_2_cpu",
                is_deleted=False,
            )
        ]
        second_sources = [
            SimpleNamespace(
                id=7,
                updated_at=datetime(2026, 6, 4, 10, 5, 0),
                detector_model_key="builtin_yolox_s_cpu",
                tracker_model_key="builtin_bytetrack",
                anomaly_stage_1_model_key="siglip_stage_1_cpu",
                anomaly_stage_2_model_key="lm_studio_stage_2",
                is_deleted=False,
            )
        ]

        external_routes.get_registry_bundle(db, source_rows=first_sources)
        external_routes.get_registry_bundle(db, source_rows=second_sources)

        self.assertEqual(mock_sync_plugin_catalog.call_count, 2)
        self.assertEqual(mock_sync_registry_bundle.call_count, 2)
        self.assertEqual(db.commit.call_count, 2)

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


if __name__ == "__main__":
    unittest.main()
