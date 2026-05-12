from types import SimpleNamespace
import unittest
from unittest.mock import patch

from shared.utils.telegram_notifications import (
    build_trigger_notification_text,
    deliver_telegram_trigger_notifications,
)


class TelegramNotificationTests(unittest.TestCase):
    def test_build_trigger_notification_text_includes_core_fields(self):
        message = build_trigger_notification_text(
            trigger_id="ALERT-12",
            trigger_type="ALERT",
            display_title="Alert: bag",
            run_identifier="run-1",
            source_label="Gate 1",
            camera_id=3,
            alert_level="High",
            occurred_at="2026-05-06T12:00:00Z",
            metadata={"matched_target": "BAG", "confidence": 0.91},
        )

        self.assertIn("Hearthlight Trigger: Alert: bag", message)
        self.assertIn("Trigger ID: ALERT-12", message)
        self.assertIn("Run: run-1", message)
        self.assertIn("Source: Gate 1", message)
        self.assertIn("Camera ID: 3", message)
        self.assertIn("Matched Target: BAG", message)
        self.assertIn("Confidence: 0.91", message)

    def test_deliver_telegram_trigger_notifications_reports_failures(self):
        subscriptions = [
            SimpleNamespace(
                subscription_label="Ops",
                bot_token="123:abc",
                chat_id="-1001",
            )
        ]

        with patch(
            "shared.utils.telegram_notifications.send_telegram_message",
            side_effect=RuntimeError("telegram rejected the message"),
        ):
            errors = deliver_telegram_trigger_notifications(
                subscriptions,
                trigger_text="hello",
            )

        self.assertEqual(len(errors), 1)
        self.assertIn("Ops", errors[0])
        self.assertIn("telegram rejected the message", errors[0])


if __name__ == "__main__":
    unittest.main()
