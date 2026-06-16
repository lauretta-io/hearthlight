import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from shared.models.APIModels import LaurettaAnomalySubmissionRequest
from src.webapp.routes import external_routes
from src.shared.models import SQLModels


class _QueryStub:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter_by(self, **kwargs):
        filtered = []
        for row in self._rows:
            if all(getattr(row, key, None) == value for key, value in kwargs.items()):
                filtered.append(row)
        return _QueryStub(filtered)

    def order_by(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _DBStub:
    def __init__(self):
        self.added = []
        self.committed = False

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.committed = True

    def refresh(self, row):
        if getattr(row, "id", None) is None:
            row.id = len(self.added)

    def query(self, model):
        table_name = getattr(model, "__tablename__", None)
        return _QueryStub([
            row
            for row in self.added
            if getattr(row.__class__, "__tablename__", None) == table_name
        ])


class HearthlightIngressApiTests(unittest.TestCase):
    def setUp(self):
        external_routes.ingress_tables_ready = False

    def tearDown(self):
        external_routes.ingress_tables_ready = False

    def test_create_submission_persists_prompt_asset_and_usage_without_raw_secret(self):
        db = _DBStub()
        request = SimpleNamespace(headers={"Authorization": "Bearer secret-client-key"})
        payload = LaurettaAnomalySubmissionRequest.model_validate(
            {
                "camera_id": 7,
                "user_id": "user-1",
                "prompt_template": "Detect unattended bags.",
                "expected_results_text": "Return JSON.",
                "image_attachments": [
                    {
                        "media_type": "image/jpeg",
                        "data_base64": "ZnJhbWUtYnl0ZXM=",
                        "width": 1280,
                        "height": 720,
                        "metadata": {"frame": 1},
                    }
                ],
                "metadata": {"source": "unit-test", "queue_only": True},
            }
        )

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {"HEARTHLIGHT_OBJECT_STORE_DIR": tmpdir},
            clear=False,
        ), patch.object(external_routes, "ensure_hearthlight_ingress_tables"):
            response = external_routes.create_hearthlight_anomaly_submission(
                payload,
                request,
                db,
            )

        submissions = [row for row in db.added if isinstance(row, SQLModels.HearthlightSubmission)]
        assets = [row for row in db.added if isinstance(row, SQLModels.SubmissionAsset)]
        ledger = [row for row in db.added if isinstance(row, SQLModels.UsageLedger)]
        encoded_response = response.model_dump_json()

        self.assertTrue(db.committed)
        self.assertEqual(len(submissions), 1)
        self.assertEqual(len(assets), 1)
        self.assertEqual(len(ledger), 2)
        self.assertEqual(submissions[0].camera_id, 7)
        self.assertEqual(submissions[0].prompt_text, "Detect unattended bags.")
        self.assertEqual(submissions[0].expected_results_text, "Return JSON.")
        self.assertEqual(submissions[0].processed_bucket, "1mp")
        self.assertEqual(submissions[0].token_units_final, 2)
        self.assertEqual({entry.event_type for entry in ledger}, {"reservation", "final"})
        self.assertNotIn("secret-client-key", encoded_response)
        self.assertNotEqual(submissions[0].client_key_hash, "secret-client-key")
        self.assertEqual(response.status, "completed")
        self.assertEqual(response.provider_status, "skipped")
        self.assertEqual(response.assets[0].size_bytes, len(b"frame-bytes"))

    def test_create_submission_forwards_to_openai_compatible_provider(self):
        db = _DBStub()
        request = SimpleNamespace(headers={"Authorization": "Bearer client-secret"})
        payload = LaurettaAnomalySubmissionRequest.model_validate(
            {
                "camera_id": 3,
                "user_id": "user-provider",
                "prompt_text": "Detect loitering.",
                "expected_results_text": "Return JSON.",
                "image_attachments": [],
                "metadata": {"provider_key": "openai"},
            }
        )

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "title": "Loitering",
                                            "category": "loitering",
                                            "score": 0.82,
                                            "reasoning": "Provider result.",
                                            "visible_items": ["person"],
                                            "visible_activities": ["standing"],
                                        }
                                    )
                                }
                            }
                        ]
                    }
                ).encode("utf-8")

        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            captured["authorization"] = req.get_header("Authorization")
            captured["timeout"] = timeout
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _Response()

        with patch.object(external_routes, "ensure_hearthlight_ingress_tables"), patch.object(
            external_routes,
            "select_anomaly_llm_model_provider_for_smoke",
            return_value={
                "provider_key": "openai",
                "enabled": True,
                "base_url": "https://api.example/v1",
                "model_name": "gpt-test",
                "timeout_seconds": 12,
                "auth_optional": False,
                "api_key": "provider-secret",
            },
        ), patch.object(external_routes.urllib_request, "urlopen", side_effect=fake_urlopen):
            response = external_routes.create_hearthlight_anomaly_submission(
                payload,
                request,
                db,
            )

        submissions = [row for row in db.added if isinstance(row, SQLModels.HearthlightSubmission)]
        encoded_response = response.model_dump_json()

        self.assertEqual(captured["url"], "https://api.example/v1/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer provider-secret")
        self.assertEqual(captured["timeout"], 12)
        self.assertEqual(captured["body"]["model"], "gpt-test")
        self.assertEqual(response.provider_key, "openai")
        self.assertEqual(response.provider_status, "completed")
        self.assertEqual(response.result["title"], "Loitering")
        self.assertEqual(submissions[0].provider_status, "completed")
        self.assertNotIn("provider-secret", encoded_response)
        self.assertNotIn("client-secret", encoded_response)

    def test_configured_ingress_client_rejects_invalid_key(self):
        db = _DBStub()
        db.add(
            SQLModels.IngressClient(
                client_label="client-a",
                client_key_hash=external_routes.hash_secret_value("valid-secret"),
                enabled=True,
                is_deleted=False,
            )
        )
        request = SimpleNamespace(headers={"Authorization": "Bearer invalid-secret"})
        payload = LaurettaAnomalySubmissionRequest.model_validate(
            {
                "camera_id": 1,
                "prompt_text": "Detect anomalies.",
                "metadata": {"queue_only": True},
            }
        )

        with patch.object(external_routes, "ensure_hearthlight_ingress_tables"), self.assertRaisesRegex(
            Exception,
            "invalid ingress client key",
        ):
            external_routes.create_hearthlight_anomaly_submission(payload, request, db)

    def test_configured_ingress_client_accepts_valid_key_and_meters_client_hash(self):
        db = _DBStub()
        client_hash = external_routes.hash_secret_value("valid-secret")
        db.add(
            SQLModels.IngressClient(
                client_label="client-a",
                client_key_hash=client_hash,
                enabled=True,
                quota_640x480=10,
                is_deleted=False,
            )
        )
        request = SimpleNamespace(headers={"Authorization": "Bearer valid-secret"})
        payload = LaurettaAnomalySubmissionRequest.model_validate(
            {
                "camera_id": 1,
                "prompt_text": "Detect anomalies.",
                "metadata": {"queue_only": True},
            }
        )

        with patch.object(external_routes, "ensure_hearthlight_ingress_tables"):
            response = external_routes.create_hearthlight_anomaly_submission(payload, request, db)

        ledger = [row for row in db.added if isinstance(row, SQLModels.UsageLedger)]
        self.assertEqual(response.provider_status, "skipped")
        self.assertEqual({row.client_key_hash for row in ledger}, {client_hash})

    def test_ingress_client_quota_rejects_over_limit_before_submission(self):
        db = _DBStub()
        client_hash = external_routes.hash_secret_value("valid-secret")
        db.add(
            SQLModels.IngressClient(
                client_label="client-a",
                client_key_hash=client_hash,
                enabled=True,
                quota_640x480=1,
                is_deleted=False,
            )
        )
        db.add(
            SQLModels.UsageLedger(
                submission_id="prior",
                client_key_hash=client_hash,
                bucket="640x480",
                token_units=1,
                event_type="final",
                is_deleted=False,
            )
        )
        request = SimpleNamespace(headers={"Authorization": "Bearer valid-secret"})
        payload = LaurettaAnomalySubmissionRequest.model_validate(
            {
                "camera_id": 1,
                "prompt_text": "Detect anomalies.",
                "metadata": {"queue_only": True},
            }
        )

        with patch.object(external_routes, "ensure_hearthlight_ingress_tables"), self.assertRaisesRegex(
            Exception,
            "daily quota exceeded",
        ):
            external_routes.create_hearthlight_anomaly_submission(payload, request, db)

        submissions = [row for row in db.added if isinstance(row, SQLModels.HearthlightSubmission)]
        self.assertEqual(submissions, [])

    def test_ingress_client_daily_quota_ignores_prior_day_usage(self):
        db = _DBStub()
        client_hash = external_routes.hash_secret_value("valid-secret")
        db.add(
            SQLModels.IngressClient(
                client_label="client-a",
                client_key_hash=client_hash,
                enabled=True,
                quota_640x480=1,
                is_deleted=False,
            )
        )
        db.add(
            SQLModels.UsageLedger(
                submission_id="yesterday",
                client_key_hash=client_hash,
                bucket="640x480",
                token_units=1,
                event_type="final",
                created_at=datetime.now(timezone.utc) - timedelta(days=1),
                is_deleted=False,
            )
        )
        request = SimpleNamespace(headers={"Authorization": "Bearer valid-secret"})
        payload = LaurettaAnomalySubmissionRequest.model_validate(
            {
                "camera_id": 1,
                "prompt_text": "Detect anomalies.",
                "metadata": {"queue_only": True},
            }
        )

        with patch.object(external_routes, "ensure_hearthlight_ingress_tables"):
            response = external_routes.create_hearthlight_anomaly_submission(payload, request, db)

        submissions = [row for row in db.added if isinstance(row, SQLModels.HearthlightSubmission)]
        self.assertEqual(response.status, "completed")
        self.assertEqual(len(submissions), 1)

    def test_get_submission_returns_persisted_status_and_assets(self):
        db = _DBStub()
        submission = SQLModels.HearthlightSubmission(
            submission_id="sub-test",
            status="completed",
            camera_id=2,
            user_id="user-2",
            prompt_raw_json=json.dumps({"prompt_text": "Prompt"}),
            prompt_text="Prompt",
            expected_results_text="Expected",
            metadata_json=json.dumps({}),
            result_json=json.dumps({"title": "Done"}),
            processed_bucket="640x480",
            token_units_reserved=1,
            token_units_final=1,
            is_deleted=False,
        )
        asset = SQLModels.SubmissionAsset(
            submission_id="sub-test",
            asset_role="original",
            media_type="image/jpeg",
            object_key="submissions/sub-test/attachment-1.bin",
            checksum_sha256="abc123",
            size_bytes=10,
            metadata_json=json.dumps({"frame": 1}),
            is_deleted=False,
        )
        db.add(submission)
        db.add(asset)

        with patch.object(external_routes, "ensure_hearthlight_ingress_tables"):
            response = external_routes.get_hearthlight_anomaly_submission("sub-test", db)

        self.assertEqual(response.submission_id, "sub-test")
        self.assertEqual(response.status, "completed")
        self.assertEqual(response.result["title"], "Done")
        self.assertEqual(response.assets[0].metadata["frame"], 1)

    def test_get_submission_asset_reads_persisted_object_bytes(self):
        db = _DBStub()
        submission = SQLModels.HearthlightSubmission(
            submission_id="sub-test",
            status="completed",
            camera_id=2,
            user_id="user-2",
            prompt_raw_json=json.dumps({"prompt_text": "Prompt"}),
            prompt_text="Prompt",
            expected_results_text="Expected",
            metadata_json=json.dumps({}),
            result_json=json.dumps({"title": "Done"}),
            processed_bucket="640x480",
            token_units_reserved=1,
            token_units_final=1,
            is_deleted=False,
        )
        asset = SQLModels.SubmissionAsset(
            submission_id="sub-test",
            asset_role="original",
            media_type="image/jpeg",
            object_key="submissions/sub-test/attachment-1.bin",
            checksum_sha256="checksum",
            size_bytes=len(b"frame-bytes"),
            metadata_json=json.dumps({"frame": 1}),
            is_deleted=False,
        )
        db.add(submission)
        db.add(asset)

        with tempfile.TemporaryDirectory() as tmpdir, patch.dict(
            os.environ,
            {
                "HEARTHLIGHT_OBJECT_STORE_BACKEND": "filesystem",
                "HEARTHLIGHT_OBJECT_STORE_DIR": tmpdir,
            },
            clear=False,
        ), patch.object(external_routes, "ensure_hearthlight_ingress_tables"):
            path = os.path.join(tmpdir, asset.object_key)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(b"frame-bytes")
            response = external_routes.get_hearthlight_anomaly_submission_asset("sub-test", 0, db)

        self.assertEqual(response.body, b"frame-bytes")
        self.assertEqual(response.media_type, "image/jpeg")
        self.assertEqual(response.headers["x-hearthlight-asset-object-key"], asset.object_key)

    def test_create_submission_can_persist_assets_to_s3_compatible_store(self):
        db = _DBStub()
        fake_s3_client = Mock()
        fake_boto3 = SimpleNamespace(client=Mock(return_value=fake_s3_client))
        request = SimpleNamespace(headers={"Authorization": "Bearer secret-client-key"})
        payload = LaurettaAnomalySubmissionRequest.model_validate(
            {
                "camera_id": 7,
                "user_id": "user-1",
                "prompt_text": "Detect unattended bags.",
                "image_attachments": [
                    {
                        "media_type": "image/jpeg",
                        "data_base64": "ZnJhbWUtYnl0ZXM=",
                        "width": 640,
                        "height": 480,
                    }
                ],
                "metadata": {"queue_only": True},
            }
        )

        with patch.dict(
            os.environ,
            {
                "HEARTHLIGHT_OBJECT_STORE_BACKEND": "s3",
                "HEARTHLIGHT_OBJECT_STORE_S3_BUCKET": "hearthlight-assets",
                "HEARTHLIGHT_OBJECT_STORE_S3_ENDPOINT_URL": "http://minio:9000",
                "HEARTHLIGHT_OBJECT_STORE_S3_ACCESS_KEY_ID": "minio",
                "HEARTHLIGHT_OBJECT_STORE_S3_SECRET_ACCESS_KEY": "secret",
            },
            clear=False,
        ), patch.dict(sys.modules, {"boto3": fake_boto3}), patch.object(
            external_routes,
            "ensure_hearthlight_ingress_tables",
        ):
            response = external_routes.create_hearthlight_anomaly_submission(payload, request, db)

        fake_boto3.client.assert_called_once_with(
            "s3",
            endpoint_url="http://minio:9000",
            region_name=None,
            aws_access_key_id="minio",
            aws_secret_access_key="secret",
        )
        fake_s3_client.put_object.assert_called_once()
        put_kwargs = fake_s3_client.put_object.call_args.kwargs
        self.assertEqual(put_kwargs["Bucket"], "hearthlight-assets")
        self.assertTrue(put_kwargs["Key"].startswith(f"submissions/{response.submission_id}/"))
        self.assertEqual(put_kwargs["Body"], b"frame-bytes")
        self.assertEqual(response.assets[0].object_key, put_kwargs["Key"])

    def test_read_submission_object_supports_s3_compatible_store(self):
        body = SimpleNamespace(read=Mock(return_value=b"frame-bytes"))
        fake_s3_client = Mock()
        fake_s3_client.get_object.return_value = {"Body": body}
        fake_boto3 = SimpleNamespace(client=Mock(return_value=fake_s3_client))

        with patch.dict(
            os.environ,
            {
                "HEARTHLIGHT_OBJECT_STORE_BACKEND": "s3",
                "HEARTHLIGHT_OBJECT_STORE_S3_BUCKET": "hearthlight-assets",
                "HEARTHLIGHT_OBJECT_STORE_S3_ENDPOINT_URL": "http://minio:9000",
                "HEARTHLIGHT_OBJECT_STORE_S3_ACCESS_KEY_ID": "minio",
                "HEARTHLIGHT_OBJECT_STORE_S3_SECRET_ACCESS_KEY": "secret",
            },
            clear=False,
        ), patch.dict(sys.modules, {"boto3": fake_boto3}):
            content = external_routes.read_submission_object("submissions/sub-test/attachment-1.bin")

        self.assertEqual(content, b"frame-bytes")
        fake_s3_client.get_object.assert_called_once_with(
            Bucket="hearthlight-assets",
            Key="submissions/sub-test/attachment-1.bin",
        )


if __name__ == "__main__":
    unittest.main()
