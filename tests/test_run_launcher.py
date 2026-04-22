import tempfile
import unittest
from pathlib import Path

from run.launcher import (
    ACTIVE_CONFIG_PATH,
    GENERATED_CONFIG_DIR,
    LaunchSelection,
    build_effective_config,
    extract_registry_model_names,
    get_nested_scalar,
    get_top_level_block,
    list_config_templates,
    read_current_selection,
    set_top_level_block,
    set_nested_scalar,
)


class LauncherHelpersTests(unittest.TestCase):
    def test_extract_registry_model_names_contains_known_entries(self):
        names = extract_registry_model_names()
        self.assertIn("dfine-x-11-05-2024", names)
        self.assertIn("rtmo-s", names)

    def test_set_nested_scalar_replaces_existing_value(self):
        text = (
            "tracking:\n"
            "  tracker: cmtrack\n"
            "rtdetr:\n"
            "  model_name: dfine-x-1280\n"
        )
        updated = set_nested_scalar(text, ["tracking"], "tracker", "strongsort")
        self.assertEqual(get_nested_scalar(updated, ["tracking"], "tracker"), "strongsort")

    def test_set_nested_scalar_inserts_nested_value(self):
        text = "output:\n  visualize:\n    mosaic: true\n"
        updated = set_nested_scalar(text, ["output", "visualize"], "show_vid", False)
        self.assertEqual(get_nested_scalar(updated, ["output", "visualize"], "show_vid"), "false")

    def test_set_nested_scalar_creates_missing_section(self):
        text = "logging:\n  level: INFO\n"
        updated = set_nested_scalar(text, ["feature_extractor"], "device", "cpu")
        self.assertEqual(get_nested_scalar(updated, ["feature_extractor"], "device"), "cpu")

    def test_list_config_templates_includes_example(self):
        templates = list_config_templates()
        self.assertIn("example", templates)
        self.assertTrue(templates["example"].exists())

    def test_set_top_level_block_replaces_existing_section(self):
        text = "input:\n  cameras: {}\ntracking:\n  tracker: cmtrack\n"
        updated = set_top_level_block(text, "input", "input:\n  cameras:\n    0:\n      name: camera_0\n")
        self.assertEqual(
            get_top_level_block(updated, "input"),
            "input:\n  cameras:\n    0:\n      name: camera_0\n",
        )

    def test_set_top_level_block_appends_missing_section(self):
        text = "tracking:\n  tracker: cmtrack\n"
        updated = set_top_level_block(text, "passenger_zones", "passenger_zones: {}\n")
        self.assertTrue(updated.endswith("passenger_zones: {}\n"))

    def test_read_current_selection_includes_pose_enable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "pose:\n"
                "  enable: true\n"
                "output:\n"
                "  visualize:\n"
                "    show_vid: false\n"
            )
            current = read_current_selection(config_path)
            self.assertEqual(current["pose_enable"], "true")
            self.assertEqual(current["show_vid"], "false")

    def test_build_effective_config_dry_run_does_not_activate(self):
        original_active = ACTIVE_CONFIG_PATH.read_text() if ACTIVE_CONFIG_PATH.exists() else None
        GENERATED_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as temp_dir:
            template_path = Path(temp_dir) / "template.yaml"
            template_path.write_text(
                "tracking:\n"
                "  tracker: cmtrack\n"
                "rtdetr:\n"
                "  model_name: dfine-x-1280\n"
                "pose:\n"
                "  enable: false\n"
                "  model_name: rtmo-s\n"
                "feature_extractor:\n"
                "  model_name: transformer_120\n"
                "output:\n"
                "  visualize:\n"
                "    show_vid: true\n"
            )
            selection = LaunchSelection(
                template_path=template_path,
                source_preset_path=None,
                run_mode="api",
                detector_model="dfine-x-11-05-2024",
                tracker_model="cmtrack",
                detector_device="cpu",
                pose_enabled=False,
                pose_model="rtmo-s",
                pose_device="cpu",
                feature_extractor_model="transformer_120",
                feature_extractor_device="cpu",
                show_video=False,
                use_cuda=False,
                cuda_visible_devices="",
                reload=False,
                skip_reset_db=True,
                open_dashboard=False,
            )
            generated_path, active_path = build_effective_config(selection, activate=False)
            self.assertTrue(generated_path.exists())
            self.assertEqual(active_path, ACTIVE_CONFIG_PATH)
            if original_active is not None:
                self.assertEqual(ACTIVE_CONFIG_PATH.read_text(), original_active)

    def test_build_effective_config_can_apply_source_preset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_dir_path = Path(temp_dir)
            template_path = temp_dir_path / "template.yaml"
            source_preset_path = temp_dir_path / "source.yaml"
            template_path.write_text(
                "input:\n"
                "  cameras:\n"
                "    0:\n"
                "      name: base_camera\n"
                "passenger_zones: {}\n"
                "tray_zones: {}\n"
                "tracking:\n"
                "  tracker: cmtrack\n"
                "rtdetr:\n"
                "  model_name: dfine-x-1280\n"
                "pose:\n"
                "  enable: false\n"
                "  model_name: rtmo-s\n"
                "feature_extractor:\n"
                "  model_name: transformer_120\n"
                "output:\n"
                "  visualize:\n"
                "    show_vid: true\n"
            )
            source_preset_path.write_text(
                "input:\n"
                "  cameras:\n"
                "    7:\n"
                "      name: preset_camera\n"
                "      source: rtsp://preset\n"
                "passenger_zones:\n"
                "  1:\n"
                "    name: zone_a\n"
                "tray_zones: {}\n"
            )
            selection = LaunchSelection(
                template_path=template_path,
                source_preset_path=source_preset_path,
                run_mode="pipeline",
                detector_model="dfine-x-11-05-2024",
                tracker_model="cmtrack",
                detector_device="cpu",
                pose_enabled=False,
                pose_model="rtmo-s",
                pose_device="cpu",
                feature_extractor_model="transformer_120",
                feature_extractor_device="cpu",
                show_video=False,
                use_cuda=False,
                cuda_visible_devices="",
                reload=False,
                skip_reset_db=True,
                open_dashboard=False,
            )
            generated_path, _ = build_effective_config(selection, activate=False)
            generated_text = generated_path.read_text()
            self.assertIn("source_preset:", generated_text)
            self.assertIn("preset_camera", generated_text)
            self.assertNotIn("base_camera", generated_text)
            self.assertIn("zone_a", generated_text)


if __name__ == "__main__":
    unittest.main()
