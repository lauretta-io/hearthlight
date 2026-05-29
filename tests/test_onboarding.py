import tempfile
import unittest
from types import SimpleNamespace
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
    configure_selected_third_party_model_env,
    detect_runtime_profile_recommendation,
    detect_system_package_plan,
    load_workspace_model_catalog,
    persist_workspace_mounted_models,
    resolve_bootstrap_python,
    resolve_selected_mounted_models,
    write_notification_env_defaults,
    write_runtime_profile_env_defaults,
)
from hearthlight.runtime import resolve_start_defaults
from hearthlight.workspace import resolve_workspace


class OnboardingTests(unittest.TestCase):
    def test_parser_includes_onboard_command(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "onboard",
                "--yes",
                "--skip-system-packages",
                "--force-env",
                "--skip-notification-setup",
                "--mount-model",
                "chatgpt_api_stage_2",
                "--openai-api-key",
                "test-key",
                "--openai-model-name",
                "gpt-5.4-mini",
                "--lm-studio-api-base-url",
                "http://localhost:1234/v1",
                "--lm-studio-model-name",
                "qwen3-local",
            ]
        )
        self.assertEqual(args.command, "onboard")
        self.assertTrue(args.yes)
        self.assertTrue(args.skip_system_packages)
        self.assertTrue(args.force_env)
        self.assertTrue(args.skip_notification_setup)
        self.assertEqual(args.mount_model, ["chatgpt_api_stage_2"])
        self.assertEqual(args.openai_api_key, "test-key")
        self.assertEqual(args.openai_model_name, "gpt-5.4-mini")
        self.assertEqual(args.lm_studio_api_base_url, "http://localhost:1234/v1")
        self.assertEqual(args.lm_studio_model_name, "qwen3-local")

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

    def test_resolve_selected_mounted_models_supports_stage_prefixed_and_plain_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            registry_dir = workspace / "shared" / "configs" / "registries"
            registry_dir.mkdir(parents=True)
            (workspace / "shared" / "configs" / "model_bindings.yaml").write_text(
                "defaults:\n"
                "  detector: builtin_yolox_s_cpu\n"
                "  tracker: builtin_bytetrack\n"
                "  anomaly_stage_1: siglip_stage_1_cpu\n"
                "  anomaly_stage_2: smolvlm_stage_2_cpu\n"
            )
            (registry_dir / "detectors.yaml").write_text("builtin_yolox_s_cpu: {}\n")
            (registry_dir / "trackers.yaml").write_text("builtin_bytetrack: {}\n")
            (registry_dir / "anomaly_stage_1_models.yaml").write_text("siglip_stage_1_cpu: {}\n")
            (registry_dir / "anomaly_stage_2_models.yaml").write_text(
                "smolvlm_stage_2_cpu: {}\nchatgpt_api_stage_2: {}\n"
            )
            args = SimpleNamespace(
                mount_default_models=True,
                mount_model=["chatgpt_api_stage_2", "detector:builtin_yolox_s_cpu"],
            )
            selected = resolve_selected_mounted_models(workspace, args)
        self.assertEqual(selected["detector"], ["builtin_yolox_s_cpu"])
        self.assertEqual(selected["tracker"], ["builtin_bytetrack"])
        self.assertEqual(selected["anomaly_stage_1"], ["siglip_stage_1_cpu"])
        self.assertEqual(selected["anomaly_stage_2"], ["smolvlm_stage_2_cpu", "chatgpt_api_stage_2"])

    def test_configure_selected_third_party_model_env_requires_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / ".env").write_text("")
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                configure_selected_third_party_model_env(
                    workspace,
                    {"anomaly_stage_2": ["chatgpt_api_stage_2"]},
                    SimpleNamespace(
                        yes=True,
                        openai_api_key="",
                        openai_model_name="",
                        anthropic_api_key="",
                        anthropic_model_name="",
                        lauretta_api_key="",
                        lauretta_api_base_url="",
                        lauretta_model_name="",
                    ),
                )

    def test_configure_selected_third_party_model_env_accepts_cli_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / ".env").write_text("")
            updates = configure_selected_third_party_model_env(
                workspace,
                {"anomaly_stage_2": ["chatgpt_api_stage_2", "lauretta_api_stage_2"]},
                SimpleNamespace(
                    yes=True,
                    openai_api_key="openai-test",
                    openai_model_name="gpt-5.4-mini",
                    anthropic_api_key="",
                    anthropic_model_name="",
                    lauretta_api_key="lauretta-test",
                    lauretta_api_base_url="https://api.lauretta.test/v1",
                    lauretta_model_name="lauretta-anomaly-stage-2",
                ),
            )
        self.assertEqual(
            updates,
            {
                "OPENAI_API_KEY": "openai-test",
                "OPENAI_MODEL_NAME": "gpt-5.4-mini",
                "LAURETTA_API_KEY": "lauretta-test",
                "LAURETTA_API_BASE_URL": "https://api.lauretta.test/v1",
                "LAURETTA_MODEL_NAME": "lauretta-anomaly-stage-2",
            },
        )

    def test_configure_selected_lm_studio_env_uses_defaults_without_api_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            (workspace / ".env").write_text("")
            updates = configure_selected_third_party_model_env(
                workspace,
                {"anomaly_stage_2": ["lm_studio_stage_2"]},
                SimpleNamespace(
                    yes=True,
                    openai_api_key="",
                    openai_model_name="",
                    anthropic_api_key="",
                    anthropic_model_name="",
                    lm_studio_api_key="",
                    lm_studio_api_base_url="",
                    lm_studio_model_name="",
                    lauretta_api_key="",
                    lauretta_api_base_url="",
                    lauretta_model_name="",
                ),
            )
        self.assertEqual(
            updates,
            {
                "LM_STUDIO_API_BASE_URL": "http://localhost:1234/v1",
                "LM_STUDIO_MODEL_NAME": "local-model",
            },
        )

    def test_persist_workspace_mounted_models_writes_selected_inventory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            path = persist_workspace_mounted_models(
                workspace,
                {
                    "detector": ["builtin_yolox_s_cpu"],
                    "tracker": [],
                    "anomaly_stage_1": ["siglip_stage_1_cpu"],
                    "anomaly_stage_2": ["chatgpt_api_stage_2"],
                },
            )
            text = path.read_text()
        self.assertIn("builtin_yolox_s_cpu", text)
        self.assertIn("chatgpt_api_stage_2", text)

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
