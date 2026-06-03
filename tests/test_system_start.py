import unittest
from unittest import mock
from unittest.mock import patch

from src.webapp.routes import external_routes


class SystemStartTests(unittest.TestCase):
    def setUp(self):
        external_routes.run_id = None
        external_routes.status = external_routes.SystemStatus.IDLE
        external_routes.module_status = {
            external_routes.ModuleNames.INGESTOR: external_routes.DataModels.Status.IDLE,
            external_routes.ModuleNames.ANOMALY: external_routes.DataModels.Status.RUNNING,
        }

    def test_pipeline_run_is_active_false_when_only_anomaly_is_running(self):
        self.assertFalse(external_routes.pipeline_run_is_active())

    def test_execute_system_start_allowed_when_anomaly_daemon_is_running(self):
        db = mock.Mock()
        runtime_cfg = mock.Mock()
        runtime_cfg.output.output_dir = "/tmp/run"
        with patch.object(external_routes, "refresh_runtime_status", return_value=external_routes.SystemStatus.IDLE):
            with patch.object(external_routes, "get_current_resource_snapshot", return_value={"admission": {"allowed": True}}):
                with patch.object(external_routes, "is_hybrid_local_cpu_runtime", return_value=False):
                    with patch.object(
                        external_routes,
                        "build_runtime_cfg",
                        return_value=(runtime_cfg, [mock.Mock(enabled=True, upload_id=None)]),
                    ):
                        with patch.object(external_routes, "ensure_run_row"):
                            with patch.object(external_routes, "sync_upload_lifecycle_states"):
                                with patch.object(external_routes, "publish_system_message"):
                                    with patch.object(external_routes, "log_resource_event"):
                                        result = external_routes.execute_system_start(db)
        self.assertEqual(result["status"], "starting")
        self.assertIsNotNone(external_routes.run_id)

    def test_get_status_stays_idle_without_run_when_ingestor_is_idle(self):
        db = unittest.mock.Mock()
        external_routes.module_status[external_routes.ModuleNames.ANOMALY] = (
            external_routes.DataModels.Status.RUNNING
        )
        snapshot = {
            "module_status": {
                external_routes.ModuleNames.INGESTOR: external_routes.DataModels.Status.IDLE,
                external_routes.ModuleNames.ANOMALY: external_routes.DataModels.Status.RUNNING,
            },
            "admission": {"allowed": True, "reason": None, "thresholds": {}, "source_errors": [], "dependency_errors": []},
            "cpu_percent": 0,
            "memory_percent": 0,
            "disk_percent": 0,
            "process_rss_mb": 0,
            "process_python_heap_mb": 0,
            "process_thread_count": 0,
            "process_open_file_descriptors": 0,
            "output_disk_usage_bytes": 0,
            "gpus": [],
            "module_metrics": {},
            "dependency_status": {},
            "model_health": {},
            "drift": {"state": "stable", "alerts": []},
            "updated_at": "2026-06-03T00:00:00+00:00",
        }
        with patch.object(external_routes, "refresh_runtime_status", return_value=external_routes.SystemStatus.IDLE):
            with patch.object(external_routes, "get_cached_resource_snapshot", return_value=snapshot):
                with patch.object(external_routes, "merge_hybrid_operator_status", return_value=snapshot["module_status"]):
                    with patch.object(external_routes, "build_source_responses", return_value=[]):
                        status_response = external_routes.get_status(db)
        self.assertEqual(status_response.status, external_routes.SystemStatus.IDLE)
        self.assertIsNone(status_response.run_id)


if __name__ == "__main__":
    unittest.main()
