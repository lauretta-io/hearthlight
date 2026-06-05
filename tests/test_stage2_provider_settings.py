import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from shared.utils.connector_endpoints import MASKED_SECRET_VALUE
from shared.utils.stage2_provider_settings import (
    Stage2ProviderSettingsDecryptError,
    Stage2ProviderSettingsKeyUnavailable,
    build_runtime_stage2_provider_settings,
    decrypt_secret_payload,
    encrypt_secret_payload,
    merge_stage2_provider_settings_draft,
    redact_stage2_provider_settings_payload,
)


class Stage2ProviderSettingsUtilityTests(unittest.TestCase):
    def test_encrypt_and_decrypt_round_trip(self):
        with patch.dict(os.environ, {"WEBAPP_SECRET_ENCRYPTION_KEY": "unit-test-key"}, clear=False):
            token = encrypt_secret_payload({"api_key": "secret-123"})
            payload = decrypt_secret_payload(token)
        self.assertEqual(payload["api_key"], "secret-123")

    def test_decrypt_rejects_invalid_ciphertext(self):
        with patch.dict(os.environ, {"WEBAPP_SECRET_ENCRYPTION_KEY": "unit-test-key"}, clear=False):
            with self.assertRaises(Stage2ProviderSettingsDecryptError):
                decrypt_secret_payload("not-a-valid-fernet-token")

    def test_write_requires_encryption_key(self):
        with patch.dict(os.environ, {}, clear=False):
            prior = os.environ.pop("WEBAPP_SECRET_ENCRYPTION_KEY", None)
            try:
                with self.assertRaises(Stage2ProviderSettingsKeyUnavailable):
                    encrypt_secret_payload({"api_key": "secret-123"})
            finally:
                if prior is not None:
                    os.environ["WEBAPP_SECRET_ENCRYPTION_KEY"] = prior

    def test_masked_secret_merge_preserves_existing_secret(self):
        merged = merge_stage2_provider_settings_draft(
            "openai",
            {
                "provider_key": "openai",
                "enabled": True,
                "base_url": "https://api.openai.com/v1",
                "model_name": "gpt-5.4-mini",
                "api_key": MASKED_SECRET_VALUE,
            },
            existing_payload={
                "provider_key": "openai",
                "enabled": True,
                "base_url": "https://api.openai.com/v1",
                "model_name": "gpt-5.4-mini",
                "api_key": "saved-secret",
            },
        )
        self.assertEqual(merged["api_key"], "saved-secret")

    def test_lm_studio_enabled_config_allows_blank_api_key(self):
        merged = merge_stage2_provider_settings_draft(
            "lm_studio",
            {
                "provider_key": "lm_studio",
                "enabled": True,
                "base_url": "http://localhost:1234/v1",
                "model_name": "qwen-local",
                "api_key": "",
            },
            existing_payload={
                "provider_key": "lm_studio",
                "enabled": False,
                "base_url": "http://localhost:1234/v1",
                "model_name": "qwen-local",
                "api_key": "",
            },
        )
        self.assertEqual(merged["api_key"], "")
        self.assertTrue(merged["auth_optional"])

    def test_runtime_resolution_prefers_saved_secure_settings_over_env(self):
        with patch.dict(
            os.environ,
            {
                "WEBAPP_SECRET_ENCRYPTION_KEY": "unit-test-key",
                "OPENAI_API_KEY": "env-secret",
                "OPENAI_BASE_URL": "https://env.example/v1",
                "OPENAI_MODEL_NAME": "env-model",
            },
            clear=False,
        ):
            row = SimpleNamespace(
                provider_key="openai",
                config_json=json.dumps(
                    {
                        "enabled": True,
                        "base_url": "https://saved.example/v1",
                        "model_name": "saved-model",
                        "timeout_seconds": 42,
                        "auth_optional": False,
                    }
                ),
                secret_json_encrypted=encrypt_secret_payload({"api_key": "saved-secret"}),
            )
            with patch("shared.utils.stage2_provider_settings.ensure_stage2_provider_setting_tables"), patch(
                "shared.utils.stage2_provider_settings.get_stage2_provider_row",
                return_value=row,
            ):
                payload = build_runtime_stage2_provider_settings(object(), "openai")
        self.assertEqual(payload["base_url"], "https://saved.example/v1")
        self.assertEqual(payload["model_name"], "saved-model")
        self.assertEqual(payload["api_key"], "saved-secret")
        self.assertEqual(payload["timeout_seconds"], 42)

    def test_redacted_payload_never_returns_raw_secret(self):
        redacted = redact_stage2_provider_settings_payload(
            {
                "provider_key": "claude_compatible",
                "enabled": True,
                "base_url": "https://claude.example/v1",
                "model_name": "claude-compatible-anomaly",
                "timeout_seconds": 30,
                "auth_optional": False,
                "auth_token": "super-secret-token",
            }
        )
        self.assertEqual(redacted["auth_token"], MASKED_SECRET_VALUE)
        self.assertTrue(redacted["secret_present"])


if __name__ == "__main__":
    unittest.main()
