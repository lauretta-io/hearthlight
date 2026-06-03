import threading
import unittest
from unittest.mock import MagicMock, patch

from shared.rabbit_messenger import Publisher


class PublisherThreadSafetyTests(unittest.TestCase):
    @patch("shared.rabbit_messenger.get_connection")
    @patch("shared.rabbit_messenger.get_rabbit_settings", return_value=("localhost", 5672, "test"))
    def test_publish_serializes_calls_across_threads(self, _mock_settings, mock_get_connection):
        channel = MagicMock()
        connection = MagicMock()
        connection.is_open = True
        mock_get_connection.return_value = (channel, connection)

        publisher = Publisher("TEST_ROUTE", create_queue=False)
        errors = []

        def publish_many():
            try:
                for _ in range(20):
                    publisher.publish(MagicMock(model_dump_json=lambda: "{}"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=publish_many) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        self.assertEqual(errors, [])
        self.assertGreater(channel.basic_publish.call_count, 0)
        publisher.close()


if __name__ == "__main__":
    unittest.main()
