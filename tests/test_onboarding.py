import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hearthlight.cli import build_parser, main
from hearthlight.onboarding import (
    RuntimeProfileRecommendation,
    apply_runtime_profile_defaults,
    check_host_tools,
    configure_notification_env_interactively,
    copy_example_env,
    copy_example_config,
    detect_runtime_profile_recommendation,
    detect_system_package_plan,
    resolve_bootstrap_python,
    write_notification_env_defaults,
    write_runtime_profile_env_defaults,
)
from hearthlight.runtime import resolve_start_defaults
from hearthlight.workspace import resolve_workspace


class OnboardingTests(unittest.TestCase):
    def test_parser_includes_onboard_command(self):
        parser = build_parser()
        args = parser.parse_args(["onboard", "--yes", "--skip-system-packages", "--force-env", "--skip-notification-setup"])
        self.assertEqual(args.command, "onboard")
        self.assertTrue(args.yes)
        self.assertTrue(args.skip_system_packages)
        self.assertTrue(args.force_env)
        self.assertTrue(args.skip_notification_setup)

    def test_detect_system_package_plan_for_apt(self):
        with (
            patch("hearthlight.onboarding._libpq_available", return_value=False),
            patch("hearthlight.onboarding._python_headers_available", return_value=False),
            patch("hearthlight.onboarding.platform.system", return_value="Linux"),
            patch("hearthlight.onboarding.shutil.which") as which_mock,
        ):
            which_mock.side_effect = lambda name: "/usr/bin/apt-get" if name == "apt-get" else None
            plan = detect_system_package_plan()
        self.assertEqual(plan.manager, "apt-get")
        self.assertIn("libpq-dev", plan.packages)
        self.assertIn("python3-dev", plan.packages)
        self.assertTrue(plan.command)

    def test_detect_runtime_profile_recommendation_defaults_to_cpu(self):
        with patch("hearthlight.onboarding.shutil.which", return_value=None):
            recommendation = detect_runtime_profile_recommendation()
        self.assertEqual(recommendation.profile, "cpu")
        self.assertEqual(recommendation.detector_device, "cpu")

    def test_check_host_tools_skips_docker_when_infra_init_is_skipped(self):
        with patch("hearthlight.onboarding.shutil.which", side_effect=lambda name: "/usr/bin/git" if name == "git" else None):
            missing = check_host_tools(require_docker=False)
        self.assertEqual(missing, [])

    def test_resolve_bootstrap_python_prefers_host_python_when_frozen(self):
        with (
            patch("hearthlight.onboarding.sys.frozen", True, create=True),
            patch("hearthlight.onboarding.shutil.which", side_effect=lambda name: "/usr/bin/python3" if name == "python3" else None),
        ):
            self.assertEqual(resolve_bootstrap_python(), "/usr/bin/python3")

    def test_copy_example_config_overwrites_when_forced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir)
            config_dir = root_dir / "shared" / "configs"
            config_dir.mkdir(parents=True)
            (config_dir / "example_config.yaml").write_text("demo: example\n")
            (config_dir / "config.yaml").write_text("demo: active\n")
            copied_path, copied = copy_example_config(root_dir, force=True)
            self.assertTrue(copied)
            self.assertEqual(copied_path.read_text(), "demo: example\n")

    def test_copy_example_env_preserves_existing_without_force(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir)
            (root_dir / "example.env").write_text("A=1\n")
            (root_dir / ".env").write_text("A=2\n")
            env_path, copied = copy_example_env(root_dir, force=False)
            self.assertFalse(copied)
            self.assertEqual(env_path.read_text(), "A=2\n")

    def test_apply_runtime_profile_defaults_sets_devices(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "rtdetr:\n"
                "  device: cuda\n"
                "pose:\n"
                "  device: cuda\n"
                "feature_extractor:\n"
                "  device: cuda:0\n"
            )
            recommendation = RuntimeProfileRecommendation(
                profile="cpu",
                detector_device="cpu",
                pose_device="cpu",
                feature_extractor_device="cpu",
                cuda_visible_devices="",
                reason="test",
            )
            apply_runtime_profile_defaults(config_path, recommendation)
            text = config_path.read_text()
            self.assertIn("device: cpu", text)

    def test_write_runtime_profile_env_defaults_are_read_by_cli_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir)
            recommendation = detect_runtime_profile_recommendation()
            write_runtime_profile_env_defaults(root_dir, recommendation)
            defaults = resolve_start_defaults(root_dir)
            self.assertEqual(defaults["profile"], recommendation.profile)
            self.assertEqual(defaults["detector_device"], recommendation.detector_device)

    def test_write_notification_env_defaults_adds_telegram_and_apple_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir)
            write_notification_env_defaults(root_dir)
            env_text = (root_dir / ".env").read_text()
            self.assertIn("TELEGRAM_BOT_TOKEN=", env_text)
            self.assertIn("APPLE_MESSAGES_RECIPIENT=", env_text)

    def test_configure_notification_env_interactively_skips_prompts_in_yes_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir)
            path = configure_notification_env_interactively(root_dir, assume_yes=True)
            self.assertTrue(path.exists())
            env_text = path.read_text()
            self.assertIn("TELEGRAM_TRIGGER_SUBSCRIPTION_ENABLED=false", env_text)

    def test_resolve_workspace_prefers_explicit_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / "docker-compose.yaml").write_text("services: {}\n")
            (workspace / "hearthlight").mkdir()
            (workspace / "shared" / "configs").mkdir(parents=True)
            (workspace / "shared" / "configs" / "example_config.yaml").write_text("demo: true\n")
            resolved = resolve_workspace(str(workspace))
            self.assertEqual(resolved, workspace.resolve())

    def test_cli_proxies_when_workspace_differs_from_package_root(self):
        with (
            patch("hearthlight.cli.resolve_workspace", return_value=Path("/tmp/hearthlight")),
            patch("hearthlight.cli._proxy_to_workspace", return_value=0) as proxy_mock,
            patch("hearthlight.cli.ROOT_DIR", Path("/tmp/site-package-root")),
        ):
            result = main(["status", "--workspace", "/tmp/hearthlight"])
        self.assertEqual(result, 0)
        proxy_mock.assert_called_once()

    def test_cli_defaults_to_interactive_start_when_no_args_are_provided(self):
        with (
            patch("hearthlight.cli.resolve_workspace", return_value=Path("/tmp/site-package-root")),
            patch("hearthlight.cli.ROOT_DIR", Path("/tmp/site-package-root")),
            patch("hearthlight.cli.build_interactive_selection", return_value="selection") as selection_mock,
            patch("hearthlight.cli.start_stack", return_value=0) as start_mock,
        ):
            result = main([])
        self.assertEqual(result, 0)
        selection_mock.assert_called_once()
        start_mock.assert_called_once_with("selection", dry_run=False)


if __name__ == "__main__":
    unittest.main()
