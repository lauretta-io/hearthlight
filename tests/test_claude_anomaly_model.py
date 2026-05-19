import unittest
import sys
import types
from pathlib import Path
from unittest.mock import patch

repo_root = Path(__file__).resolve().parents[1]
package = types.ModuleType("hearthlight_repo")
package.__path__ = [str(repo_root)]
sys.modules["hearthlight_repo"] = package

from hearthlight_repo.anomaly.adapters import (
    ClaudeCompatibleStageTwoAdapter,
    PromptBundle,
    StageOneCandidate,
)
from shared.utils.claude_anomaly_model import (
    DEFAULT_CLAUDE_ANOMALY_MODEL_NAME,
    build_claude_anomaly_request,
    default_claude_anomaly_model_config,
    merge_claude_anomaly_model_secret_config,
    parse_claude_anomaly_response,
    redact_claude_anomaly_model_config,
    send_claude_anomaly_request,
    validate_claude_anomaly_model_config,
)
from shared.utils.connector_endpoints import MASKED_SECRET_VALUE


class ClaudeAnomalyModelTests(unittest.TestCase):
    def test_config_validation_redacts_and_preserves_secret(self):
        config = validate_claude_anomaly_model_config(
            {
                "enabled": True,
                "base_url": "http://localhost:8788/v1/messages",
                "auth_token": "secret",
                "timeout_seconds": "15",
                "retry_count": "2",
            }
        )
        redacted = redact_claude_anomaly_model_config(config)
        merged = merge_claude_anomaly_model_secret_config(
            {"auth_token": "secret"},
            {"auth_token": MASKED_SECRET_VALUE, "base_url": "http://localhost:8788/v1/messages"},
        )

        self.assertEqual(config["model_name"], DEFAULT_CLAUDE_ANOMALY_MODEL_NAME)
        self.assertEqual(config["timeout_seconds"], 15)
        self.assertEqual(config["retry_count"], 2)
        self.assertEqual(redacted["auth_token"], MASKED_SECRET_VALUE)
        self.assertEqual(merged["auth_token"], "secret")

    def test_request_payload_contains_candidate_context(self):
        payload = build_claude_anomaly_request(
            config=default_claude_anomaly_model_config(),
            event_id="evt-1",
            run_id="run-1",
            source_id=5,
            camera_id=2,
            frame_id=99,
            stage_1_model_key="heuristic_presence_stage_1",
            stage_2_model_key="claude_compatible_stage_2",
            candidate_category="presence_resume",
            candidate_score=0.7,
            candidate_reasoning="Observed people and bags.",
            visible_items=["person", "bag"],
            visible_activities=["presence resume"],
            prompt_template="Return JSON.",
            anomaly_object_list=["bag"],
            anomaly_activity_list=["loitering"],
        )

        candidate = payload["hearthlight"]["candidate"]
        self.assertEqual(payload["messages"][0]["role"], "user")
        self.assertEqual(payload["metadata"]["purpose"], "anomaly_detection")
        self.assertEqual(candidate["event_id"], "evt-1")
        self.assertEqual(candidate["visible_items"], ["person", "bag"])
        self.assertEqual(payload["hearthlight"]["prompt"]["anomaly_object_list"], ["bag"])

    def test_request_payload_renders_prompt_placeholders(self):
        payload = build_claude_anomaly_request(
            config=default_claude_anomaly_model_config(),
            event_id="evt-1",
            run_id="run-1",
            source_id=5,
            camera_id=2,
            frame_id=99,
            stage_1_model_key="heuristic_presence_stage_1",
            stage_2_model_key="claude_compatible_stage_2",
            candidate_category="presence_resume",
            candidate_score=0.7,
            candidate_reasoning="Observed people and bags.",
            visible_items=["person", "bag"],
            visible_activities=["presence resume"],
            prompt_template=(
                "Review {frames_count} frames. Frames: {input_details}. "
                "Items: {anomaly_object_list}. Activities: {anomaly_activity_list}."
            ),
            anomaly_object_list=["bag", "weapon"],
            anomaly_activity_list=["loitering"],
        )

        message_text = payload["messages"][0]["content"][0]["text"]
        rendered_template = payload["hearthlight"]["prompt"]["template"]
        self.assertIn("Review 1 frames", message_text)
        self.assertIn("Items: bag, weapon", message_text)
        self.assertIn('"candidate_category": "presence_resume"', message_text)
        self.assertNotIn("{frames_count}", rendered_template)
        self.assertNotIn("{input_details}", rendered_template)

    def test_response_parsing_supports_claude_content_json(self):
        parsed = parse_claude_anomaly_response(
            {
                "content": [
                    {
                        "type": "text",
                        "text": '{"promote": true, "category": "unattended_bag", "title": "Unattended Bag", "score": 0.91, "reasoning": "Bag remains visible.", "visible_items": ["bag"], "visible_activities": ["standing nearby"]}',
                    }
                ]
            }
        )

        self.assertTrue(parsed["promote"])
        self.assertEqual(parsed["category"], "unattended_bag")
        self.assertEqual(parsed["score"], 0.91)
        self.assertEqual(parsed["visible_items"], ["bag"])

    def test_response_parsing_honors_string_false_promote(self):
        parsed = parse_claude_anomaly_response(
            {
                "promote": "false",
                "category": "normal_activity",
                "score": 0.99,
            }
        )

        self.assertFalse(parsed["promote"])

    def test_response_parsing_supports_prompt_contract_fields(self):
        parsed = parse_claude_anomaly_response(
            {
                "confidence": 0.9,
                "anomaly_detected": True,
                "anomaly_category": "vehicle",
                "visible_items": "car, truck",
                "visible_activities": "vehicle driving",
            }
        )

        self.assertTrue(parsed["promote"])
        self.assertEqual(parsed["category"], "vehicle")
        self.assertEqual(parsed["visible_items"], ["car", "truck"])
        self.assertEqual(parsed["visible_activities"], ["vehicle driving"])

    def test_response_parsing_does_not_promote_low_confidence_by_default(self):
        parsed = parse_claude_anomaly_response({"confidence": 0.2, "category": "normal"})

        self.assertFalse(parsed["promote"])

    def test_send_request_error_is_raised_for_unreachable_server(self):
        config = validate_claude_anomaly_model_config(
            {
                "enabled": True,
                "base_url": "http://example.invalid/v1/messages",
                "timeout_seconds": 1,
                "retry_count": 0,
            }
        )
        with patch("shared.utils.claude_anomaly_model.urllib_request.urlopen") as urlopen:
            urlopen.side_effect = TimeoutError("timed out")
            with self.assertRaisesRegex(RuntimeError, "claude anomaly model request failed"):
                send_claude_anomaly_request(config, {"messages": []})

    def test_adapter_maps_api_response_into_anomaly_event(self):
        adapter = ClaudeCompatibleStageTwoAdapter(
            {
                "runtime": {},
            }
        )
        candidate = StageOneCandidate(
            event_id="evt-1",
            run_id="run-1",
            source_id=4,
            camera_id=2,
            frame_id=12,
            stage_1_model_key="heuristic_presence_stage_1",
            stage_2_model_key="claude_compatible_stage_2",
            category="presence_resume",
            score=0.65,
            reasoning="Candidate detected.",
            visible_items=["person"],
            visible_activities=["presence resume"],
            asset_references=[],
        )
        prompts = PromptBundle(
            template="Return JSON.",
            anomaly_object_list=["bag"],
            anomaly_activity_list=["loitering"],
        )
        config = {
            **default_claude_anomaly_model_config(),
            "enabled": True,
            "base_url": "http://localhost:8788/v1/messages",
        }
        result = {
            "promote": True,
            "category": "anomaly_event",
            "title": "Unexpected Activity",
            "score": 0.88,
            "reasoning": "External model promoted it.",
            "visible_items": ["person", "bag"],
            "visible_activities": ["unexpected activity"],
        }

        with patch.object(adapter, "_load_config", return_value=config), patch(
            "hearthlight_repo.anomaly.adapters.send_claude_anomaly_request",
            return_value=result,
        ):
            event = adapter.build_event(candidate=candidate, prompts=prompts)

        self.assertIsNotNone(event)
        self.assertEqual(event.model_key, "claude_compatible_stage_2")
        self.assertEqual(event.category, "anomaly_event")
        self.assertEqual(event.score, 0.88)
        self.assertEqual(event.visible_items, ["person", "bag"])


if __name__ == "__main__":
    unittest.main()
