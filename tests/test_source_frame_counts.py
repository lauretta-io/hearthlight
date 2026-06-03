import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.webapp.routes import external_routes


class SourceFrameCountTests(unittest.TestCase):
    def test_build_input_source_response_uses_ingestor_processed_frames(self):
        source_row = SimpleNamespace(
            id=1,
            kind="camera_url",
            label="Camera 1",
            tasks=["PERSON"],
            enabled=True,
            sort_order=0,
            source_value="http://example.test/stream.mjpg",
            upload_id=None,
            frame_processing_mode="frame_skip",
            process_every_n_frames=1,
            target_frame_rate=None,
            detector_model_key=None,
            tracker_model_key=None,
            reid_model_key=None,
            anomaly_stage_1_model_key=None,
            anomaly_stage_2_model_key=None,
            last_error=None,
        )
        with patch.object(external_routes, "status", external_routes.SystemStatus.RUNNING), patch.object(
            external_routes,
            "frame_id",
            None,
        ), patch.object(
            external_routes,
            "module_runtime_details",
            {
                external_routes.ModuleNames.INGESTOR: {
                    "sources": {
                        "1": {
                            "processed_frames": 42,
                            "capture_fps": 5.0,
                            "processed_fps": 2.5,
                            "skipped_frames": 3,
                        }
                    }
                }
            },
        ), patch.object(
            external_routes,
            "normalize_frame_processing_settings",
            return_value={
                "frame_processing_mode": "frame_skip",
                "process_every_n_frames": 1,
                "target_frame_rate": None,
            },
        ), patch.object(external_routes, "build_effective_source_error", return_value=None):
            response = external_routes.build_input_source_response(
                source_row,
                None,
                None,
                {"updated_at": "2026-06-03T15:00:00+00:00"},
            )

        self.assertEqual(response.frames_processed, 42)
        self.assertEqual(response.processed_fps, 2.5)
        self.assertEqual(response.skipped_frames, 3)
