from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from shared.models import DataModels
from shared.database.database_worker import DatabaseWorker
from shared.utils.alert_rules import (
    ALERT_SIGNAL_FAMILY_ANOMALY_ACTIVITY,
    ALERT_SIGNAL_FAMILY_ANOMALY_OBJECT,
    ALERT_SIGNAL_FAMILY_DETECTOR,
    build_alert_rule_option_catalog,
    get_detector_rule_targets,
    parse_anomaly_type_prompt_yaml,
)


class AlertRuleUtilityTests(unittest.TestCase):
    def test_get_detector_rule_targets_maps_yolox_artifact_classes(self):
        registration = {
            "artifact_ref": "yolox-s",
            "capabilities": {},
        }

        targets = get_detector_rule_targets(registration)

        self.assertEqual(targets, [{"key": "PERSON", "label": "PERSON"}, {"key": "BAG", "label": "BAG"}])

    def test_build_alert_rule_option_catalog_marks_detector_unavailable_without_classes(self):
        bundle = {
            "models": {
                "detector": {
                    "custom_detector": {
                        "artifact_ref": None,
                        "capabilities": {},
                    },
                },
            },
            "bindings": {
                "defaults": {
                    "detector": "custom_detector",
                    "tracker": None,
                    "reid": None,
                    "anomaly_stage_1": None,
                    "anomaly_stage_2": None,
                },
            },
        }
        source_row = SimpleNamespace(
            id=4,
            label="North Gate",
            detector_model_key=None,
            tracker_model_key=None,
            reid_model_key=None,
            anomaly_stage_1_model_key=None,
            anomaly_stage_2_model_key=None,
        )

        catalog = build_alert_rule_option_catalog(
            bundle=bundle,
            source_rows=[source_row],
            anomaly_type_yaml="anomaly_object_list:\n  - weapon\nanomaly_activity_list:\n  - running\n",
            has_gpu=False,
        )

        detector_options = catalog["sources"][0]["signal_options"][0]
        self.assertEqual(detector_options["signal_family"], ALERT_SIGNAL_FAMILY_DETECTOR)
        self.assertEqual(detector_options["options"], [])
        self.assertIn("Please select and save a detector model", detector_options["unavailable_reason"])

    def test_parse_anomaly_type_prompt_yaml_reads_lists(self):
        parsed = parse_anomaly_type_prompt_yaml(
            "anomaly_object_list:\n  - weapon\nanomaly_activity_list:\n  - running\n"
        )

        self.assertEqual(parsed["anomaly_object_list"], ["weapon"])
        self.assertEqual(parsed["anomaly_activity_list"], ["running"])


class DatabaseWorkerAlertRuleTests(unittest.TestCase):
    def setUp(self):
        self.worker = DatabaseWorker()
        self.worker.create_alert_incident = Mock()

    def test_detector_rule_match_below_threshold_does_not_trigger(self):
        self.worker.get_source_template_id_for_camera = Mock(return_value=12)
        self.worker.get_enabled_alert_rules = Mock(
            return_value=[
                SimpleNamespace(id=7, target_key="PERSON", min_confidence=0.8, alert_level="high"),
            ]
        )
        self.worker.resolve_model_keys_for_source = Mock(return_value={"detector": "builtin_yolox_s_cpu"})
        track = DataModels.TrackInstance(
            track_id=91,
            bbox=[0, 0, 10, 10],
            cam_id=2,
            clss="PERSON",
            confidence=0.5,
            timestamp=1.0,
            frame_id=8,
        )

        self.worker.maybe_create_detector_alerts(track)

        self.worker.create_alert_incident.assert_not_called()

    def test_detector_rule_match_above_threshold_triggers_alert(self):
        self.worker.get_source_template_id_for_camera = Mock(return_value=12)
        self.worker.get_enabled_alert_rules = Mock(
            return_value=[
                SimpleNamespace(id=7, target_key="PERSON", min_confidence=0.4, alert_level="high"),
            ]
        )
        self.worker.resolve_model_keys_for_source = Mock(return_value={"detector": "builtin_yolox_s_cpu"})
        track = DataModels.TrackInstance(
            track_id=91,
            bbox=[0, 0, 10, 10],
            cam_id=2,
            clss="PERSON",
            confidence=0.85,
            timestamp=1.0,
            frame_id=8,
        )

        self.worker.maybe_create_detector_alerts(track)

        self.worker.create_alert_incident.assert_called_once()
        self.assertEqual(
            self.worker.create_alert_incident.call_args.kwargs["signal_family"],
            ALERT_SIGNAL_FAMILY_DETECTOR,
        )

    def test_anomaly_object_match_above_threshold_triggers_alert(self):
        self.worker.get_enabled_alert_rules = Mock(
            side_effect=lambda **kwargs: [
                SimpleNamespace(id=22, target_key="weapon", min_confidence=0.5, alert_level="medium")
            ] if kwargs["signal_family"] == ALERT_SIGNAL_FAMILY_ANOMALY_OBJECT else []
        )
        event = DataModels.AnomalyEvent(
            event_id="evt-1",
            source_id=3,
            camera_id=1,
            frame_id=7,
            stage_1_model_key="heuristic_presence_stage_1",
            stage_2_model_key="prompt_rules_stage_2",
            model_key="prompt_rules_stage_2",
            category="weapon visible",
            score=0.9,
            visible_items=["weapon"],
            visible_activities=[],
        )

        self.worker.maybe_create_anomaly_alerts(event)

        self.worker.create_alert_incident.assert_called_once()
        self.assertEqual(
            self.worker.create_alert_incident.call_args.kwargs["signal_family"],
            ALERT_SIGNAL_FAMILY_ANOMALY_OBJECT,
        )

    def test_anomaly_activity_match_above_threshold_triggers_alert(self):
        self.worker.get_enabled_alert_rules = Mock(
            side_effect=lambda **kwargs: [
                SimpleNamespace(id=31, target_key="running", min_confidence=0.4, alert_level="low")
            ] if kwargs["signal_family"] == ALERT_SIGNAL_FAMILY_ANOMALY_ACTIVITY else []
        )
        event = DataModels.AnomalyEvent(
            event_id="evt-2",
            source_id=3,
            camera_id=1,
            frame_id=7,
            stage_1_model_key="heuristic_presence_stage_1",
            stage_2_model_key="prompt_rules_stage_2",
            model_key="prompt_rules_stage_2",
            category="running",
            score=0.75,
            visible_items=[],
            visible_activities=["running"],
        )

        self.worker.maybe_create_anomaly_alerts(event)

        self.worker.create_alert_incident.assert_called_once()
        self.assertEqual(
            self.worker.create_alert_incident.call_args.kwargs["signal_family"],
            ALERT_SIGNAL_FAMILY_ANOMALY_ACTIVITY,
        )

    def test_disabled_rules_do_not_trigger(self):
        self.worker.get_source_template_id_for_camera = Mock(return_value=12)
        self.worker.get_enabled_alert_rules = Mock(return_value=[])
        track = DataModels.TrackInstance(
            track_id=91,
            bbox=[0, 0, 10, 10],
            cam_id=2,
            clss="PERSON",
            confidence=0.95,
            timestamp=1.0,
            frame_id=8,
        )

        self.worker.maybe_create_detector_alerts(track)

        self.worker.create_alert_incident.assert_not_called()
