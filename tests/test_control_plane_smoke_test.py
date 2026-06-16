import unittest
from unittest.mock import patch

from scripts import control_plane_smoke_test


def _model_options_payload(mounted_overrides=None):
    mounted = {
        "detector": ["builtin_yolox_s_cpu"],
        "tracker": ["builtin_bytetrack"],
        "anomaly_stage_1": ["siglip_stage_1_cpu"],
        "anomaly_stage_2": ["smolvlm_stage_2_cpu"],
    }
    if mounted_overrides:
        mounted.update(mounted_overrides)
    return {
        "mounted_models": mounted,
        "stages": [
            {
                "stage": "detector",
                "options": [{"model_key": "builtin_yolox_s_cpu"}],
            },
            {
                "stage": "tracker",
                "options": [{"model_key": "builtin_bytetrack"}],
            },
            {
                "stage": "anomaly_stage_1",
                "options": [{"model_key": "siglip_stage_1_cpu"}],
            },
            {
                "stage": "anomaly_stage_2",
                "options": [{"model_key": "smolvlm_stage_2_cpu"}],
            },
        ],
    }


def _bindings_payload():
    return [
        {
            "stage": "detector",
            "model_key": "builtin_yolox_s_cpu",
            "binding_scope": "default",
            "resolved": True,
        },
        {
            "stage": "tracker",
            "model_key": "builtin_bytetrack",
            "binding_scope": "default",
            "resolved": True,
        },
        {
            "stage": "anomaly_stage_1",
            "model_key": "siglip_stage_1_cpu",
            "binding_scope": "default",
            "resolved": True,
        },
        {
            "stage": "anomaly_stage_2",
            "model_key": "smolvlm_stage_2_cpu",
            "binding_scope": "default",
            "resolved": True,
        },
    ]


class ControlPlaneSmokeTestTests(unittest.TestCase):
    def test_validate_model_registry_defaults_accepts_resolved_mounted_defaults(self):
        responses = {
            "/model-options": _model_options_payload(),
            "/model-bindings": _bindings_payload(),
        }

        with patch.object(
            control_plane_smoke_test,
            "send_json",
            side_effect=lambda _base_url, path, **_kwargs: responses[path],
        ):
            model_options, bindings = control_plane_smoke_test.validate_model_registry_defaults(
                "http://example.test/api",
                None,
            )

        self.assertEqual(model_options["mounted_models"]["detector"], ["builtin_yolox_s_cpu"])
        self.assertEqual(len(bindings), 4)

    def test_validate_model_registry_defaults_rejects_unmounted_default(self):
        responses = {
            "/model-options": _model_options_payload({"detector": []}),
            "/model-bindings": _bindings_payload(),
        }

        with patch.object(
            control_plane_smoke_test,
            "send_json",
            side_effect=lambda _base_url, path, **_kwargs: responses[path],
        ):
            with self.assertRaisesRegex(RuntimeError, "detector=builtin_yolox_s_cpu is not mounted"):
                control_plane_smoke_test.validate_model_registry_defaults(
                    "http://example.test/api",
                    None,
                )


if __name__ == "__main__":
    unittest.main()
