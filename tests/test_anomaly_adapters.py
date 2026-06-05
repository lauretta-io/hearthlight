from dataclasses import replace
import json
import tempfile
import unittest
from urllib import error
from unittest.mock import patch

from anomaly.adapters import (
    ClaudeStageTwoAdapter,
    OpenAICompatibleStageTwoAdapter,
    PromptBundle,
    StageOneCandidate,
)
from shared.models.DataModels import AssetReference


class _FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _CaptureURLopener:
    def __init__(self, payload: dict | Exception):
        self.payload = payload
        self.last_request = None

    def __call__(self, req, timeout=None):
        self.last_request = req
        self.last_timeout = timeout
        if isinstance(self.payload, Exception):
            raise self.payload
        return _FakeHTTPResponse(self.payload)


class _NullSessionContext:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


class ThirdPartyStageTwoAdapterTests(unittest.TestCase):
    def setUp(self):
        self.candidate = StageOneCandidate(
            event_id="evt-1",
            run_id="run-1",
            source_id=1,
            camera_id=1,
            frame_id=42,
            stage_1_model_key="siglip_stage_1_cpu",
            stage_2_model_key="chatgpt_api_stage_2",
            category="presence_resume",
            score=0.7,
            reasoning="Stage 1 saw a candidate.",
            visible_items=["person", "backpack"],
            visible_activities=["loitering"],
            asset_references=[
                AssetReference(uri="/tmp/frame.jpg", media_type="image/jpeg", producer="ANOMALY")
            ],
        )
        self.prompts = PromptBundle(
            template="Find anomalies in the frame.",
            anomaly_object_list=["person", "backpack"],
            anomaly_activity_list=["loitering", "abandoned object"],
        )

    def test_openai_compatible_adapter_parses_remote_json_response(self):
        adapter = OpenAICompatibleStageTwoAdapter(
            {
                "runtime": {
                    "provider": "openai",
                    "model_name": "gpt-5.4-mini",
                    "model_name_env": "OPENAI_MODEL_NAME",
                    "api_key_env": "OPENAI_API_KEY",
                    "base_url": "https://api.openai.com/v1",
                }
            }
        )
        response_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "title": "Possible loitering near bag",
                                "category": "loitering",
                                "score": 8,
                                "reasoning": "The person remained near a bag.",
                                "visible_items": ["person", "backpack"],
                                "visible_activities": ["loitering"],
                            }
                        )
                    }
                }
            ]
        }
        opener = _CaptureURLopener(response_payload)
        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL_NAME": "gpt-5.5"},
            clear=False,
        ), patch("anomaly.adapters.SessionLocal", return_value=_NullSessionContext()), patch(
            "anomaly.adapters.build_runtime_stage2_provider_settings",
            return_value={
                "enabled": True,
                "base_url": "https://api.openai.com/v1",
                "model_name": "gpt-5.5",
                "timeout_seconds": 30,
                "auth_optional": False,
                "api_key": "test-key",
            },
        ), patch("anomaly.adapters.request.urlopen", side_effect=opener):
            event = adapter.build_event(candidate=self.candidate, prompts=self.prompts)
        self.assertEqual(event.title, "Possible loitering near bag")
        self.assertEqual(event.category, "loitering")
        self.assertAlmostEqual(event.score, 0.8)
        self.assertEqual(event.visible_items, ["person", "backpack"])
        self.assertEqual(opener.last_request.full_url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(opener.last_request.get_header("Authorization"), "Bearer test-key")
        payload = json.loads(opener.last_request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "gpt-5.5")
        self.assertEqual(payload["messages"][1]["role"], "user")

    def test_openai_compatible_adapter_falls_back_on_malformed_json(self):
        adapter = OpenAICompatibleStageTwoAdapter(
            {
                "runtime": {
                    "provider": "openai",
                    "model_name": "gpt-5.4-mini",
                    "api_key_env": "OPENAI_API_KEY",
                    "base_url": "https://api.openai.com/v1",
                }
            }
        )
        response_payload = {"choices": [{"message": {"content": "{not-json"}}]}
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), patch(
            "anomaly.adapters.SessionLocal", return_value=_NullSessionContext()
        ), patch(
            "anomaly.adapters.build_runtime_stage2_provider_settings",
            return_value={
                "enabled": True,
                "base_url": "https://api.openai.com/v1",
                "model_name": "gpt-5.4-mini",
                "timeout_seconds": 30,
                "auth_optional": False,
                "api_key": "test-key",
            },
        ), patch("anomaly.adapters.request.urlopen", return_value=_FakeHTTPResponse(response_payload)):
            event = adapter.build_event(candidate=self.candidate, prompts=self.prompts)
        self.assertEqual(event.model_key, "chatgpt_api_stage_2")
        self.assertIn("Stage-2 remote model was unavailable", event.reasoning or "")

    def test_openai_compatible_adapter_falls_back_on_transport_error(self):
        adapter = OpenAICompatibleStageTwoAdapter(
            {
                "runtime": {
                    "provider": "openai",
                    "model_name": "gpt-5.4-mini",
                    "api_key_env": "OPENAI_API_KEY",
                    "base_url": "https://api.openai.com/v1",
                }
            }
        )
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}, clear=False), patch(
            "anomaly.adapters.SessionLocal", return_value=_NullSessionContext()
        ), patch(
            "anomaly.adapters.build_runtime_stage2_provider_settings",
            return_value={
                "enabled": True,
                "base_url": "https://api.openai.com/v1",
                "model_name": "gpt-5.4-mini",
                "timeout_seconds": 30,
                "auth_optional": False,
                "api_key": "test-key",
            },
        ), patch("anomaly.adapters.request.urlopen", side_effect=error.URLError("network down")):
            event = adapter.build_event(candidate=self.candidate, prompts=self.prompts)
        self.assertEqual(event.category, "loitering")
        self.assertIn("Stage-2 remote model was unavailable", event.reasoning or "")

    def test_lm_studio_adapter_works_without_auth_header(self):
        candidate = replace(self.candidate, stage_2_model_key="lm_studio_stage_2")
        adapter = OpenAICompatibleStageTwoAdapter(
            {
                "runtime": {
                    "provider": "lm_studio",
                    "model_name": "qwen-local",
                    "model_name_env": "LM_STUDIO_MODEL_NAME",
                    "api_key_env": "LM_STUDIO_API_KEY",
                    "base_url": "http://localhost:1234/v1",
                    "base_url_env": "LM_STUDIO_API_BASE_URL",
                    "auth_optional": True,
                }
            }
        )
        opener = _CaptureURLopener(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "title": "Local anomaly",
                                    "category": "loitering",
                                    "score": 0.6,
                                    "reasoning": "Local model flagged loitering.",
                                    "visible_items": ["person", "backpack"],
                                    "visible_activities": ["loitering"],
                                }
                            )
                        }
                    }
                ]
            }
        )
        with patch.dict(
            "os.environ",
            {"LM_STUDIO_MODEL_NAME": "qwen3-local", "LM_STUDIO_API_BASE_URL": "http://localhost:1234/v1"},
            clear=False,
        ), patch("anomaly.adapters.SessionLocal", return_value=_NullSessionContext()), patch(
            "anomaly.adapters.build_runtime_stage2_provider_settings",
            return_value={
                "enabled": True,
                "base_url": "http://localhost:1234/v1",
                "model_name": "qwen3-local",
                "timeout_seconds": 30,
                "auth_optional": True,
                "api_key": "",
            },
        ), patch("anomaly.adapters.request.urlopen", side_effect=opener):
            event = adapter.build_event(candidate=candidate, prompts=self.prompts)
        self.assertEqual(event.model_key, "lm_studio_stage_2")
        self.assertEqual(opener.last_request.full_url, "http://localhost:1234/v1/chat/completions")
        header_map = {key.lower(): value for key, value in opener.last_request.header_items()}
        self.assertNotIn("authorization", header_map)
        payload = json.loads(opener.last_request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "qwen3-local")

    def test_openai_compatible_adapter_prefers_resolved_secure_provider_settings(self):
        adapter = OpenAICompatibleStageTwoAdapter(
            {
                "runtime": {
                    "provider": "openai",
                    "model_name": "registry-model",
                    "api_key_env": "OPENAI_API_KEY",
                    "base_url": "https://api.openai.com/v1",
                }
            }
        )
        opener = _CaptureURLopener(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "title": "Secure profile",
                                    "category": "loitering",
                                    "score": 0.8,
                                    "reasoning": "Used secure settings.",
                                    "visible_items": ["person", "backpack"],
                                    "visible_activities": ["loitering"],
                                }
                            )
                        }
                    }
                ]
            }
        )
        with patch("anomaly.adapters.SessionLocal", return_value=_NullSessionContext()), patch(
            "anomaly.adapters.build_runtime_stage2_provider_settings",
            return_value={
                "enabled": True,
                "base_url": "https://saved.example/v1",
                "model_name": "saved-model",
                "timeout_seconds": 17,
                "auth_optional": False,
                "api_key": "saved-secret",
            },
        ), patch("anomaly.adapters.request.urlopen", side_effect=opener):
            event = adapter.build_event(candidate=self.candidate, prompts=self.prompts)
        self.assertEqual(event.title, "Secure profile")
        self.assertEqual(opener.last_request.full_url, "https://saved.example/v1/chat/completions")
        self.assertEqual(opener.last_request.get_header("Authorization"), "Bearer saved-secret")
        self.assertEqual(opener.last_timeout, 17)
        payload = json.loads(opener.last_request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "saved-model")

    def test_lauretta_provider_posts_submission_payload_with_inline_images(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg") as frame_file:
            frame_file.write(b"frame-bytes")
            frame_file.flush()
            candidate = replace(
                self.candidate,
                stage_2_model_key="lauretta_api_stage_2",
                asset_references=[
                    AssetReference(uri=frame_file.name, media_type="image/jpeg", producer="ANOMALY")
                ],
            )
            adapter = OpenAICompatibleStageTwoAdapter(
                {
                    "runtime": {
                        "provider": "lauretta",
                        "model_name": "lauretta-anomaly-stage-2",
                        "api_key_env": "LAURETTA_API_KEY",
                        "base_url_env": "LAURETTA_API_BASE_URL",
                    }
                }
            )
            opener = _CaptureURLopener(
                {
                    "result": {
                        "title": "Potential loitering near bag",
                        "category": "loitering",
                        "score": 0.8,
                        "reasoning": "The person stayed in frame near the bag.",
                        "visible_items": ["person", "backpack"],
                        "visible_activities": ["loitering"],
                    }
                }
            )
            with patch.dict(
                "os.environ",
                {
                    "LAURETTA_API_KEY": "test-key",
                    "LAURETTA_API_BASE_URL": "https://lauretta.example",
                    "LAURETTA_USER_ID": "user-77",
                },
                clear=False,
            ), patch("anomaly.adapters.SessionLocal", return_value=_NullSessionContext()), patch(
                "anomaly.adapters.build_runtime_stage2_provider_settings",
                return_value={
                    "enabled": True,
                    "base_url": "https://lauretta.example",
                    "model_name": "lauretta-anomaly-stage-2",
                    "timeout_seconds": 30,
                    "auth_optional": False,
                    "api_key": "test-key",
                },
            ), patch("anomaly.adapters.request.urlopen", side_effect=opener):
                event = adapter.build_event(candidate=candidate, prompts=self.prompts)
        self.assertEqual(event.model_key, "lauretta_api_stage_2")
        self.assertEqual(opener.last_request.full_url, "https://lauretta.example/v1/hearthlight/anomaly-submissions")
        self.assertEqual(opener.last_request.get_header("Authorization"), "Bearer test-key")
        payload = json.loads(opener.last_request.data.decode("utf-8"))
        self.assertEqual(payload["user_id"], "user-77")
        self.assertEqual(payload["camera_id"], 1)
        self.assertEqual(len(payload["image_attachments"]), 1)
        self.assertEqual(payload["image_attachments"][0]["media_type"], "image/jpeg")

    def test_claude_adapter_falls_back_when_api_key_missing(self):
        candidate = replace(self.candidate, stage_2_model_key="claude_api_stage_2")
        adapter = ClaudeStageTwoAdapter(
            {
                "runtime": {
                    "provider": "anthropic",
                    "model_name": "claude-sonnet-4-6",
                    "api_key_env": "ANTHROPIC_API_KEY",
                    "base_url": "https://api.anthropic.com/v1",
                }
            }
        )
        with patch.dict("os.environ", {}, clear=True), patch(
            "anomaly.adapters.SessionLocal", return_value=_NullSessionContext()
        ), patch(
            "anomaly.adapters.build_runtime_stage2_provider_settings",
            return_value={
                "enabled": True,
                "base_url": "https://api.anthropic.com/v1",
                "model_name": "claude-sonnet-4-6",
                "timeout_seconds": 30,
                "auth_token": "",
            },
        ):
            event = adapter.build_event(candidate=candidate, prompts=self.prompts)
        self.assertEqual(event.model_key, "claude_api_stage_2")
        self.assertIn("Stage-2 remote model was unavailable", event.reasoning or "")

    def test_claude_adapter_parses_remote_json_response_and_model_override(self):
        candidate = replace(self.candidate, stage_2_model_key="claude_api_stage_2")
        adapter = ClaudeStageTwoAdapter(
            {
                "runtime": {
                    "provider": "anthropic",
                    "model_name": "claude-sonnet-4-6",
                    "model_name_env": "ANTHROPIC_MODEL_NAME",
                    "api_key_env": "ANTHROPIC_API_KEY",
                    "base_url": "https://api.anthropic.com/v1",
                }
            }
        )
        opener = _CaptureURLopener(
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "title": "Bag abandoned near platform edge",
                                "category": "abandoned object",
                                "score": 0.9,
                                "reasoning": "Bag remained alone after the person left.",
                                "visible_items": ["backpack"],
                                "visible_activities": ["abandoned object"],
                            }
                        ),
                    }
                ]
            }
        )
        with patch.dict(
            "os.environ",
            {"ANTHROPIC_API_KEY": "anthropic-test", "ANTHROPIC_MODEL_NAME": "claude-opus-4-7"},
            clear=False,
        ), patch("anomaly.adapters.SessionLocal", return_value=_NullSessionContext()), patch(
            "anomaly.adapters.build_runtime_stage2_provider_settings",
            return_value={
                "enabled": True,
                "base_url": "https://api.anthropic.com/v1",
                "model_name": "claude-opus-4-7",
                "timeout_seconds": 30,
                "auth_token": "anthropic-test",
            },
        ), patch("anomaly.adapters.request.urlopen", side_effect=opener):
            event = adapter.build_event(candidate=candidate, prompts=self.prompts)
        self.assertEqual(event.title, "Bag abandoned near platform edge")
        self.assertEqual(event.category, "abandoned object")
        self.assertAlmostEqual(event.score, 0.9)
        self.assertEqual(opener.last_request.full_url, "https://api.anthropic.com/v1/messages")
        header_map = {key.lower(): value for key, value in opener.last_request.header_items()}
        self.assertEqual(header_map.get("x-api-key"), "anthropic-test")
        self.assertEqual(header_map.get("anthropic-version"), "2023-06-01")
        payload = json.loads(opener.last_request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "claude-opus-4-7")

    def test_claude_adapter_uses_secure_provider_settings(self):
        candidate = replace(self.candidate, stage_2_model_key="claude_api_stage_2")
        adapter = ClaudeStageTwoAdapter(
            {
                "runtime": {
                    "provider": "anthropic",
                    "model_name": "claude-sonnet-4-6",
                    "api_key_env": "ANTHROPIC_API_KEY",
                    "base_url": "https://api.anthropic.com/v1",
                }
            }
        )
        opener = _CaptureURLopener(
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "title": "Claude secure profile",
                                "category": "loitering",
                                "score": 0.81,
                                "reasoning": "Used secure settings.",
                                "visible_items": ["person", "backpack"],
                                "visible_activities": ["loitering"],
                            }
                        ),
                    }
                ]
            }
        )
        with patch("anomaly.adapters.SessionLocal", return_value=_NullSessionContext()), patch(
            "anomaly.adapters.build_runtime_stage2_provider_settings",
            return_value={
                "enabled": True,
                "base_url": "https://claude-secure.example/v1",
                "model_name": "claude-saved",
                "timeout_seconds": 21,
                "auth_token": "secure-token",
            },
        ), patch("anomaly.adapters.request.urlopen", side_effect=opener):
            event = adapter.build_event(candidate=candidate, prompts=self.prompts)
        self.assertEqual(event.title, "Claude secure profile")
        self.assertEqual(opener.last_request.full_url, "https://claude-secure.example/v1/messages")
        header_map = {key.lower(): value for key, value in opener.last_request.header_items()}
        self.assertEqual(header_map.get("x-api-key"), "secure-token")
        self.assertEqual(opener.last_timeout, 21)
        payload = json.loads(opener.last_request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "claude-saved")

    def test_claude_adapter_falls_back_on_malformed_json(self):
        candidate = replace(self.candidate, stage_2_model_key="claude_api_stage_2")
        adapter = ClaudeStageTwoAdapter(
            {
                "runtime": {
                    "provider": "anthropic",
                    "model_name": "claude-sonnet-4-6",
                    "api_key_env": "ANTHROPIC_API_KEY",
                    "base_url": "https://api.anthropic.com/v1",
                }
            }
        )
        response_payload = {"content": [{"type": "text", "text": "{bad-json"}]}
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "anthropic-test"}, clear=False), patch(
            "anomaly.adapters.SessionLocal", return_value=_NullSessionContext()
        ), patch(
            "anomaly.adapters.build_runtime_stage2_provider_settings",
            return_value={
                "enabled": True,
                "base_url": "https://api.anthropic.com/v1",
                "model_name": "claude-sonnet-4-6",
                "timeout_seconds": 30,
                "auth_token": "anthropic-test",
            },
        ), patch("anomaly.adapters.request.urlopen", return_value=_FakeHTTPResponse(response_payload)):
            event = adapter.build_event(candidate=candidate, prompts=self.prompts)
        self.assertEqual(event.model_key, "claude_api_stage_2")
        self.assertIn("Stage-2 remote model was unavailable", event.reasoning or "")
