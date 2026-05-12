import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hearthlight.macos_app import resolve_dashboard_url, resolve_helper_command


class MacOSAppTests(unittest.TestCase):
    def test_resolve_dashboard_url_defaults_to_3000(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.assertEqual(
                resolve_dashboard_url(temp_dir),
                "http://localhost:3000",
            )

    def test_resolve_dashboard_url_reads_env_port(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / ".env").write_text("WEBAPP_UI_HOST_PORT=13000\n")
            self.assertEqual(
                resolve_dashboard_url(str(workspace)),
                "http://localhost:13000",
            )

    def test_resolve_helper_command_uses_frozen_helper_when_present(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            helper_path = Path(temp_dir) / "hearthlight-helper"
            helper_path.write_text("stub")
            with (
                patch("hearthlight.macos_app.sys.frozen", True, create=True),
                patch("hearthlight.macos_app.sys.executable", str(Path(temp_dir) / "Hearthlight")),
            ):
                self.assertEqual(resolve_helper_command(), [str(helper_path.resolve())])


if __name__ == "__main__":
    unittest.main()
