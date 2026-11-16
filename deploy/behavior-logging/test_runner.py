import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("behavior_runner", Path(__file__).with_name("runner.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class LoggerBoundaryTests(unittest.TestCase):
    def test_rejects_non_camera_inputs(self):
        for url in ["file:///etc/passwd", "https://example.com/image.jpg", ""]:
            with self.assertRaises(ValueError):
                runner.validate_cameras({"cameras": [{"id": "one", "name": "Office", "source": url}]})

    def test_ffmpeg_timeout_does_not_expose_camera_credentials(self):
        source = "rtsp://test:private-password@192.0.2.1:554/live"
        with patch.object(runner.subprocess, "run", side_effect=subprocess.TimeoutExpired(source, 1)):
            with self.assertRaisesRegex(RuntimeError, "^camera_connection_timeout$"):
                runner.sample_frames(source)

    def test_ffmpeg_failure_does_not_emit_stderr(self):
        result = subprocess.CompletedProcess([], 1, stderr=b"rtsp://test:private-password@192.0.2.1/live")
        with patch.object(runner.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "^camera_stream_unavailable$"):
                runner.sample_frames("rtsp://test:private-password@192.0.2.1/live")

class SamplingTests(unittest.TestCase):
    def test_configured_sample_uses_sixteen_frames_at_two_fps(self):
        from PIL import Image

        def capture(command, **kwargs):
            self.assertIn("fps=2.0,scale=640:-2", command)
            self.assertEqual(command[command.index("-frames:v") + 1], "16")
            for index in range(1, 17):
                Image.new("RGB", (64, 36)).save(command[-1].replace("%02d", f"{index:02d}"))
            return subprocess.CompletedProcess(command, 0)

        with patch.dict(runner.os.environ, {"BEHAVIOR_SAMPLE_FRAMES": "16", "BEHAVIOR_SAMPLE_FPS": "2"}):
            with patch.object(runner.subprocess, "run", side_effect=capture):
                self.assertEqual(len(runner.sample_frames("rtsp://camera.test/live")), 16)


if __name__ == "__main__":
    unittest.main()
