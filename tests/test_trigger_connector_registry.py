import unittest

from shared.utils.trigger_connector_registry import load_connector_zoo, load_trigger_zoo


class TriggerConnectorRegistryTests(unittest.TestCase):
    def test_trigger_zoo_contains_alert_and_anomaly_entries(self):
        trigger_zoo = load_trigger_zoo()
        keys = {entry["key"] for entry in trigger_zoo}
        self.assertIn("alert_rule_trigger", keys)
        self.assertIn("anomaly_event_trigger", keys)

    def test_connector_zoo_contains_messaging_and_webhook_entries(self):
        connector_zoo = load_connector_zoo()
        keys = {entry["key"] for entry in connector_zoo}
        self.assertIn("telegram", keys)
        self.assertIn("apple_messages", keys)
        self.assertIn("philips_hue", keys)
        self.assertIn("music_api", keys)
        self.assertIn("robot_action", keys)
        self.assertIn("webhook", keys)
        self.assertIn("govee", keys)


if __name__ == "__main__":
    unittest.main()
