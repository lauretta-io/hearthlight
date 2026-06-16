import unittest
from unittest.mock import patch

from webapp import run


class WebappRunTests(unittest.TestCase):
    def test_int_env_uses_positive_integer(self):
        with patch.dict("os.environ", {"API_WEB_CONCURRENCY": "12"}, clear=True):
            self.assertEqual(run.int_env("API_WEB_CONCURRENCY", 1), 12)

    def test_int_env_falls_back_for_invalid_value(self):
        with patch.dict("os.environ", {"API_WEB_CONCURRENCY": "not-a-number"}, clear=True):
            self.assertEqual(run.int_env("API_WEB_CONCURRENCY", 1), 1)


if __name__ == "__main__":
    unittest.main()
