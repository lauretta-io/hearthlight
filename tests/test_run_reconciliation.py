import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.webapp.routes import external_routes


class RunReconciliationTests(unittest.TestCase):
    def setUp(self):
        external_routes.run_id = None
        external_routes.status = external_routes.SystemStatus.IDLE
        external_routes.module_status = {
            external_routes.ModuleNames.INGESTOR: external_routes.DataModels.Status.IDLE,
            external_routes.ModuleNames.ANOMALY: external_routes.DataModels.Status.IDLE,
        }

    def test_reconcile_restores_run_id_when_ingestor_is_running(self):
        external_routes.module_status[external_routes.ModuleNames.INGESTOR] = (
            external_routes.DataModels.Status.RUNNING
        )
        run_row = SimpleNamespace(run_identifier="2026-06-03_15-34-00")
        db = SimpleNamespace()

        with patch.object(
            external_routes,
            "get_latest_active_run_row",
            return_value=run_row,
        ):
            recovered = external_routes.reconcile_active_run_from_workers(db)

        self.assertTrue(recovered)
        self.assertEqual(external_routes.run_id, "2026-06-03_15-34-00")
        self.assertEqual(external_routes.status, external_routes.SystemStatus.RUNNING)

    def test_derive_source_state_marks_running_when_ingestor_module_is_active(self):
        source_row = SimpleNamespace(enabled=True)
        snapshot = {
            "module_status": {
                external_routes.ModuleNames.INGESTOR: external_routes.DataModels.Status.RUNNING,
            }
        }
        with patch.object(external_routes, "status", external_routes.SystemStatus.IDLE):
            state = external_routes.derive_source_state(source_row, None, snapshot)
        self.assertEqual(state, "running")


if __name__ == "__main__":
    unittest.main()
