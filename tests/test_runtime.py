from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from hearthlight.runtime import resolve_local_worker_env
from src.ingestor.main import _resolve_process_every_n_frames


class RuntimeEnvTests(unittest.TestCase):
    def test_resolve_local_worker_env_maps_compose_rabbitmq_to_host_port(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "RABBITMQ_HOST=rabbitmq\n"
                "RABBITMQ_EXCHANGE=test\n"
            )
            env = resolve_local_worker_env(root)
            self.assertEqual(env["RABBITMQ_HOST"], "localhost")
            self.assertEqual(env["RABBITMQ_PORT"], "5673")

    def test_resolve_process_every_n_frames_honors_target_rate_for_live_sources(self):
        self.assertEqual(
            _resolve_process_every_n_frames(
                {
                    "source_kind": "camera_url",
                    "frame_processing_mode": "target_frame_rate",
                    "target_frame_rate": 5,
                    "process_every_n_frames": 1,
                },
                input_max_fps=20,
            ),
            4,
        )

    def test_resolve_process_every_n_frames_forces_uploaded_video_to_frame_skip(self):
        self.assertEqual(
            _resolve_process_every_n_frames(
                {
                    "source_kind": "video_upload",
                    "frame_processing_mode": "target_frame_rate",
                    "target_frame_rate": 2,
                    "process_every_n_frames": 3,
                },
                input_max_fps=20,
            ),
            3,
        )


if __name__ == "__main__":
    unittest.main()
