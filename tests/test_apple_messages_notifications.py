from types import SimpleNamespace
import unittest
from unittest.mock import patch

from shared.utils.apple_messages_notifications import (
    deliver_apple_message_trigger_notifications,
    send_apple_message,
)


class AppleMessageNotificationTests(unittest.TestCase):
    def test_deliver_apple_message_trigger_notifications_reports_failures(self):
        subscriptions = [
            SimpleNamespace(
                subscription_label="Ops iMessage",
                recipient_handle="+15551234567",
                service="iMessage",
            )
        ]

        with patch(
            "shared.utils.apple_messages_notifications.send_apple_message",
            side_effect=RuntimeError("messages rejected the message"),
        ):
            errors = deliver_apple_message_trigger_notifications(
                subscriptions,
                trigger_text="hello",
            )

        self.assertEqual(len(errors), 1)
        self.assertIn("Ops iMessage", errors[0])
        self.assertIn("messages rejected the message", errors[0])

    def test_send_apple_message_requires_macos(self):
        with patch("shared.utils.apple_messages_notifications.platform.system", return_value="Linux"):
            with self.assertRaisesRegex(RuntimeError, "only supported on macOS hosts"):
                send_apple_message(
                    recipient_handle="+15551234567",
                    text="hello",
                )


if __name__ == "__main__":
    unittest.main()
