from contextlib import redirect_stdout
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from hearthlight.runtime import (
    compose_status,
    local_worker_status,
    print_local_worker_status,
    resolve_local_worker_env,
)
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

    def test_compose_status_includes_reverse_proxy(self):
        with patch("hearthlight.runtime.find_docker_binary", return_value="/usr/local/bin/docker"), patch(
            "hearthlight.runtime.subprocess.call",
            return_value=0,
        ) as call_mock, patch("hearthlight.runtime.print_local_worker_status") as worker_status_mock:
            result = compose_status(Path("/tmp/hearthlight"), use_cuda=False)

        self.assertEqual(result, 0)
        command = call_mock.call_args.args[0]
        self.assertIn("ps", command)
        self.assertIn("webapp", command)
        self.assertIn("reverse_proxy", command)
        worker_status_mock.assert_called_once()

    def test_local_worker_status_reads_supervisor_health(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return (
                    b'{"status":"ready","runtime":"hybrid-local-mlx",'
                    b'"workers":{"INGESTOR":{"running":true,"pid":101}}}'
                )

        with patch("hearthlight.runtime.request.urlopen", return_value=FakeResponse()) as urlopen_mock:
            status = local_worker_status(Path("/tmp/hearthlight"))

        self.assertEqual(status["status"], "ready")
        self.assertEqual(status["runtime"], "hybrid-local-mlx")
        self.assertEqual(status["workers"]["INGESTOR"]["pid"], 101)
        self.assertIn("127.0.0.1:8070", urlopen_mock.call_args.args[0])

    def test_print_local_worker_status_reports_unavailable_hybrid_supervisor(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text("HEARTHLIGHT_WORKER_RUNTIME=hybrid-local-mlx\n")
            output = io.StringIO()
            with patch(
                "hearthlight.runtime.local_worker_status",
                return_value={
                    "status": "unavailable",
                    "url": "http://127.0.0.1:8070/healthz",
                    "detail": "connection refused",
                },
            ), redirect_stdout(output):
                print_local_worker_status(root, use_cuda=False)

        rendered = output.getvalue()
        self.assertIn("Local worker supervisor", rendered)
        self.assertIn("health: unavailable", rendered)
        self.assertIn("connection refused", rendered)

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
