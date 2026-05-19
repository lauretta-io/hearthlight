import unittest

from shared.utils.claude_api_connector import (
    _candidate_urls,
    build_claude_trigger_payload,
    validate_claude_api_config,
)
from shared.utils.connector_endpoints import (
    MASKED_SECRET_VALUE,
    merge_connector_endpoint_secret_config,
    redact_connector_endpoint_config,
)


class ClaudeApiConnectorTests(unittest.TestCase):
    def test_build_claude_trigger_payload_uses_messages_contract(self):
        payload = build_claude_trigger_payload(
            trigger_id="ALERT-12",
            trigger_type="alert_rule_trigger",
            trigger_text="hello",
            display_title="Alert: bag",
            run_identifier="run-1",
            source_label="Gate 1",
            camera_id=3,
            alert_level="High",
            occurred_at="2026-05-19T12:00:00Z",
            metadata={"matched_target": "BAG"},
        )

        self.assertEqual(payload["messages"][0]["role"], "user")
        self.assertEqual(payload["messages"][0]["content"][0]["type"], "text")
        self.assertEqual(payload["hearthlight"]["trigger_id"], "ALERT-12")
        self.assertEqual(payload["metadata"]["matched_target"], "BAG")

    def test_validate_claude_api_config_normalizes_retry_policy(self):
        config = validate_claude_api_config(
            {
                "base_url": "http://localhost:8787/v1/messages",
                "auth_token": "secret",
                "timeout_seconds": "15",
                "retry_count": "2",
            }
        )

        self.assertEqual(config["timeout_seconds"], 15)
        self.assertEqual(config["retry_count"], 2)

    def test_candidate_urls_bridge_host_and_container_localhost(self):
        self.assertEqual(
            _candidate_urls("http://host.docker.internal:8787/v1/messages"),
            [
                "http://host.docker.internal:8787/v1/messages",
                "http://localhost:8787/v1/messages",
            ],
        )
        self.assertEqual(
            _candidate_urls("http://localhost:8787/v1/messages"),
            [
                "http://localhost:8787/v1/messages",
                "http://host.docker.internal:8787/v1/messages",
            ],
        )

    def test_claude_secret_fields_are_redacted_and_preserved(self):
        redacted = redact_connector_endpoint_config(
            {
                "base_url": "http://localhost:8787/v1/messages",
                "auth_token": "secret",
            }
        )
        merged = merge_connector_endpoint_secret_config(
            {"auth_token": "secret"},
            {"auth_token": MASKED_SECRET_VALUE},
        )

        self.assertEqual(redacted["auth_token"], MASKED_SECRET_VALUE)
        self.assertEqual(merged["auth_token"], "secret")


if __name__ == "__main__":
    unittest.main()
