import unittest

from scripts import container_preflight


class ContainerPreflightSecurityTests(unittest.TestCase):
    def test_evaluate_env_security_warnings_flags_missing_api_key_and_origins(self):
        warnings = container_preflight.evaluate_env_security_warnings(
            {
                "POSTGRES_USER": "postgres",
                "WEBAPP_ALLOW_REMOTE_WITHOUT_API_KEY": "false",
            }
        )

        self.assertIn(
            "WEBAPP_API_KEY is not set; keep the API bound to localhost only or configure a shared key before remote exposure.",
            warnings,
        )
        self.assertIn(
            "WEBAPP_ALLOWED_ORIGINS is not set; the wider built-in localhost allowlist will be used instead of an explicit deployment-specific list.",
            warnings,
        )

    def test_evaluate_env_security_warnings_flags_remote_without_key(self):
        warnings = container_preflight.evaluate_env_security_warnings(
            {
                "WEBAPP_ALLOW_REMOTE_WITHOUT_API_KEY": "true",
                "WEBAPP_ALLOWED_ORIGINS": "http://localhost:3000",
            }
        )

        self.assertIn(
            "WEBAPP_ALLOW_REMOTE_WITHOUT_API_KEY is enabled; remote clients can reach the control-plane API without a shared key.",
            warnings,
        )

    def test_evaluate_env_security_warnings_accepts_explicit_hardened_settings(self):
        warnings = container_preflight.evaluate_env_security_warnings(
            {
                "WEBAPP_API_KEY": "secret",
                "WEBAPP_ALLOW_REMOTE_WITHOUT_API_KEY": "false",
                "WEBAPP_ALLOWED_ORIGINS": "http://localhost:3000,http://127.0.0.1:3000",
            }
        )

        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
