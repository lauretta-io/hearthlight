import unittest
from unittest.mock import Mock, patch

from shared.database import database


class DatabaseConfigTests(unittest.TestCase):
    def tearDown(self):
        database.reset_engine()

    def test_get_engine_uses_pool_size_environment_overrides(self):
        fake_engine = Mock()
        env = {
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "root",
            "POSTGRES_HOST": "pgbouncer",
            "POSTGRES_PORT": "6432",
            "POSTGRES_DB": "hearthlight",
            "DB_POOL_SIZE": "4",
            "DB_MAX_OVERFLOW": "4",
        }

        with patch.dict("os.environ", env, clear=True), patch.object(
            database,
            "create_engine",
            return_value=fake_engine,
        ) as create_engine_mock:
            self.assertIs(database.get_engine(), fake_engine)

        kwargs = create_engine_mock.call_args.kwargs
        self.assertEqual(kwargs["pool_size"], 4)
        self.assertEqual(kwargs["max_overflow"], 4)
        self.assertIn("@pgbouncer:6432/hearthlight", create_engine_mock.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
