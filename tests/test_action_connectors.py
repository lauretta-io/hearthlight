import unittest

from shared.utils.action_connectors import (
    build_action_trigger_payload,
    validate_action_connector_config,
)
from shared.utils.connector_endpoints import (
    MASKED_SECRET_VALUE,
    merge_connector_endpoint_secret_config,
    redact_connector_endpoint_config,
)


class ActionConnectorTests(unittest.TestCase):
    def test_build_action_trigger_payload_uses_stable_contract(self):
        payload = build_action_trigger_payload(
            connector_key="robot_action",
            command="move_to_zone",
            target="zone-a",
            parameters={"speed": "slow"},
            trigger_id="MANUAL-0",
            trigger_type="manual_trigger",
            display_title="Manual Demo Trigger",
            source_label="Lobby",
            alert_level="Low",
            metadata={"demo": True},
        )

        self.assertEqual(payload["schema"], "hearthlight.action.v1")
        self.assertEqual(payload["action"]["type"], "robot_action")
        self.assertEqual(payload["action"]["command"], "move_to_zone")
        self.assertEqual(payload["trigger"]["id"], "MANUAL-0")
        self.assertTrue(payload["trigger"]["metadata"]["demo"])

    def test_validate_action_connector_config_normalizes_policy(self):
        config = validate_action_connector_config(
            {
                "action_type": "music_api",
                "base_url": "http://localhost:8790/actions",
                "auth_token": "secret",
                "command": "play_alert",
                "target": "speaker-1",
                "parameters": {"playlist": "alarms"},
                "timeout_seconds": "15",
                "retry_count": "2",
            }
        )

        self.assertEqual(config["action_type"], "music_api")
        self.assertEqual(config["timeout_seconds"], 15)
        self.assertEqual(config["retry_count"], 2)

    def test_action_secret_fields_are_redacted_and_preserved(self):
        redacted = redact_connector_endpoint_config(
            {
                "base_url": "http://localhost:8790/actions",
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
