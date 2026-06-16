import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from shared.utils.connector_endpoints import MASKED_SECRET_VALUE
from shared.utils import anomaly_llm_model_settings as anomaly_llm_model_settings_module
from shared.utils.anomaly_llm_model_settings import (
    AnomalyLlmModelSettingsDecryptError,
    AnomalyLlmModelSettingsKeyUnavailable,
    build_runtime_anomaly_llm_model_settings,
    decrypt_secret_payload,
    encrypt_secret_payload,
    merge_anomaly_llm_model_settings_draft,
    redact_anomaly_llm_model_settings_payload,
    write_anomaly_llm_model_settings,
)


class AnomalyLlmModelSettingsUtilityTests(unittest.TestCase):
    def test_encrypt_and_decrypt_round_trip(self):
        with patch.dict(os.environ, {"WEBAPP_SECRET_ENCRYPTION_KEY": "unit-test-key"}, clear=False):
            token = encrypt_secret_payload({"api_key": "secret-123"})
            payload = decrypt_secret_payload(token)
        self.assertEqual(payload["api_key"], "secret-123")

    def test_decrypt_rejects_invalid_ciphertext(self):
        with patch.dict(os.environ, {"WEBAPP_SECRET_ENCRYPTION_KEY": "unit-test-key"}, clear=False):
            with self.assertRaises(AnomalyLlmModelSettingsDecryptError):
                decrypt_secret_payload("not-a-valid-fernet-token")

    def test_write_requires_encryption_key(self):
        with patch.dict(os.environ, {}, clear=False):
            prior = os.environ.pop("WEBAPP_SECRET_ENCRYPTION_KEY", None)
            try:
                with self.assertRaises(AnomalyLlmModelSettingsKeyUnavailable):
                    encrypt_secret_payload({"api_key": "secret-123"})
            finally:
                if prior is not None:
                    os.environ["WEBAPP_SECRET_ENCRYPTION_KEY"] = prior

    def test_provider_table_creation_is_process_cached(self):
        anomaly_llm_model_settings_module._ensure_tables_done = False
        try:
            with patch("shared.utils.anomaly_llm_model_settings.get_engine", return_value=object()), patch(
                "shared.utils.anomaly_llm_model_settings.SQLModels.Base.metadata.create_all",
            ) as create_all:
                anomaly_llm_model_settings_module.ensure_anomaly_llm_model_setting_tables()
                anomaly_llm_model_settings_module.ensure_anomaly_llm_model_setting_tables()
            self.assertEqual(create_all.call_count, 1)
        finally:
            anomaly_llm_model_settings_module._ensure_tables_done = False

    def test_provider_table_creation_runs_legacy_table_rename_before_create(self):
        anomaly_llm_model_settings_module._ensure_tables_done = False
        call_order = []

        class _Connection:
            dialect = SimpleNamespace(name="postgresql")

            def execute(self, statement, *_args, **_kwargs):
                call_order.append(("migrate", str(statement)))

        class _Begin:
            def __enter__(self):
                return _Connection()

            def __exit__(self, *_args):
                return None

        class _Engine:
            def begin(self):
                return _Begin()

        try:
            with patch("shared.utils.anomaly_llm_model_settings.get_engine", return_value=_Engine()), patch(
                "shared.utils.anomaly_llm_model_settings.SQLModels.Base.metadata.create_all",
                side_effect=lambda **_kwargs: call_order.append(("create", "")),
            ):
                anomaly_llm_model_settings_module.ensure_anomaly_llm_model_setting_tables()
            self.assertEqual(call_order[0][0], "migrate")
            self.assertIn("stage2" + "_provider_setting", call_order[0][1])
            self.assertEqual(call_order[1][0], "create")
        finally:
            anomaly_llm_model_settings_module._ensure_tables_done = False

    def test_masked_secret_merge_preserves_existing_secret(self):
        merged = merge_anomaly_llm_model_settings_draft(
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
        merged = merge_anomaly_llm_model_settings_draft(
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
            with patch("shared.utils.anomaly_llm_model_settings.ensure_anomaly_llm_model_setting_tables"), patch(
                "shared.utils.anomaly_llm_model_settings.get_anomaly_llm_model_provider_row",
                return_value=row,
            ):
                payload = build_runtime_anomaly_llm_model_settings(object(), "openai")
        self.assertEqual(payload["base_url"], "https://saved.example/v1")
        self.assertEqual(payload["model_name"], "saved-model")
        self.assertEqual(payload["api_key"], "saved-secret")
        self.assertEqual(payload["timeout_seconds"], 42)

    def test_redacted_payload_never_returns_raw_secret(self):
        redacted = redact_anomaly_llm_model_settings_payload(
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

    def test_write_persists_secret_as_encrypted_database_payload(self):
        row = SimpleNamespace(
            provider_key="openai",
            config_json="{}",
            secret_json_encrypted="",
            is_deleted=False,
            deleted_at=None,
        )
        db = SimpleNamespace(flush=lambda: None)
        with patch.dict(os.environ, {"WEBAPP_SECRET_ENCRYPTION_KEY": "unit-test-key"}, clear=False), patch(
            "shared.utils.anomaly_llm_model_settings.ensure_anomaly_llm_model_setting_tables",
        ), patch(
            "shared.utils.anomaly_llm_model_settings.list_anomaly_llm_model_provider_rows",
            return_value=[row],
        ):
            saved = write_anomaly_llm_model_settings(
                db,
                [
                    {
                        "provider_key": "openai",
                        "enabled": True,
                        "base_url": "https://api.openai.com/v1",
                        "model_name": "gpt-5.4-mini",
                        "timeout_seconds": 30,
                        "auth_optional": False,
                        "api_key": "new-db-secret",
                    }
                ],
            )
            decrypted = decrypt_secret_payload(row.secret_json_encrypted)

        self.assertNotIn("new-db-secret", row.config_json)
        self.assertNotIn("new-db-secret", row.secret_json_encrypted)
        self.assertEqual(decrypted["api_key"], "new-db-secret")
        self.assertEqual(saved[0]["api_key"], MASKED_SECRET_VALUE)
        self.assertTrue(saved[0]["secret_present"])


if __name__ == "__main__":
    unittest.main()
