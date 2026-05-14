import unittest

from shared.utils.connector_endpoints import (
    MASKED_SECRET_VALUE,
    merge_connector_endpoint_secret_config,
    redact_connector_endpoint_config,
)


class ConnectorSecurityTests(unittest.TestCase):
    def test_redact_connector_endpoint_config_masks_known_secret_fields(self):
        redacted = redact_connector_endpoint_config(
            {
                "bot_token": "123:secret",
                "chat_id": "-100123",
                "bearer_token": "abc",
                "url": "https://example.com/hook",
            }
        )

        self.assertEqual(redacted["bot_token"], MASKED_SECRET_VALUE)
        self.assertEqual(redacted["bearer_token"], MASKED_SECRET_VALUE)
        self.assertEqual(redacted["chat_id"], "-100123")
        self.assertEqual(redacted["url"], "https://example.com/hook")

    def test_merge_connector_endpoint_secret_config_preserves_existing_secret_on_masked_save(self):
        merged = merge_connector_endpoint_secret_config(
            {"bot_token": "123:secret", "chat_id": "-100123"},
            {"bot_token": MASKED_SECRET_VALUE, "chat_id": "-100999"},
        )

        self.assertEqual(merged["bot_token"], "123:secret")
        self.assertEqual(merged["chat_id"], "-100999")


if __name__ == "__main__":
    unittest.main()
