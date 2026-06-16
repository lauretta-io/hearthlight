import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib import error

from scripts import run_deployment_verification


class _Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class _BinaryResponse:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.payload


class DeploymentVerificationTests(unittest.TestCase):
    def _hosted_runtime_payload(self):
        return {
            "ok": True,
            "runtime_profile": {
                "api": {
                    "api_web_concurrency": "12",
                    "api_client_cache_ttl_seconds": "15",
                    "local_stack": False,
                },
                "database": {
                    "postgres_host": "pgbouncer",
                    "postgres_port": "6432",
                    "db_pool_size": "4",
                    "db_max_overflow": "4",
                },
                "worker": {
                    "worker_runtime": "docker",
                    "worker_concurrency": "32",
                    "worker_poll_seconds": "0.05",
                    "inline_inference_after_preprocess": True,
                },
                "object_store": {
                    "backend": "s3",
                    "s3_bucket": "hearthlight-assets",
                    "s3_endpoint_url": "http://minio:9000",
                    "s3_access_key_present": True,
                    "s3_secret_key_present": True,
                },
            },
        }

    def test_extract_throughput_samples_from_nested_benchmark_payload(self):
        payload = {
            "runs": [
                {"client_key": "client-a", "submissions_per_second": 210.5},
                {"client_key": "client-b", "metrics": {"rps": 205}},
            ],
            "summary": {"ignored": True},
        }

        self.assertEqual(
            run_deployment_verification.extract_throughput_samples(payload),
            [210.5, 205.0],
        )
        self.assertEqual(
            run_deployment_verification.extract_client_keys(payload),
            {"client-a", "client-b"},
        )

    def test_validate_queue_benchmarks_accepts_median_gate_with_multiple_clients(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "queue.json"
            path.write_text(json.dumps({
                "runs": [
                    {"client_key": "client-a", "submissions_per_second": 201},
                    {"client_key": "client-b", "submissions_per_second": 230},
                    {"client_key": "client-c", "submissions_per_second": 215},
                ]
            }))

            result = run_deployment_verification.validate_queue_benchmarks(
                [path],
                required_median=200,
                require_multiple_client_keys=True,
            )

        self.assertEqual(result["throughput"]["median"], 215)
        self.assertEqual(result["client_key_count"], 3)

    def test_validate_queue_benchmarks_rejects_single_client_key(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "queue.json"
            path.write_text(json.dumps({
                "runs": [
                    {"client_key": "client-a", "submissions_per_second": 250},
                    {"client_key": "client-a", "submissions_per_second": 240},
                ]
            }))

            with self.assertRaisesRegex(RuntimeError, "multiple client keys"):
                run_deployment_verification.validate_queue_benchmarks(
                    [path],
                    required_median=200,
                    require_multiple_client_keys=True,
                )

    def test_validate_queue_benchmarks_rejects_low_median(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "queue.json"
            path.write_text(json.dumps({
                "runs": [
                    {"client_key": "client-a", "submissions_per_second": 190},
                    {"client_key": "client-b", "submissions_per_second": 199},
                    {"client_key": "client-c", "submissions_per_second": 205},
                ]
            }))

            with self.assertRaisesRegex(RuntimeError, "below required"):
                run_deployment_verification.validate_queue_benchmarks(
                    [path],
                    required_median=200,
                    require_multiple_client_keys=True,
                )

    def test_summarize_settled_benchmarks_records_separate_ingress_and_settled_metrics(self):
        with TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "settled-1.json"
            second = Path(tmpdir) / "settled-2.json"
            first.write_text(json.dumps({
                "failure_count": 0,
                "settled_failure_count": 0,
                "ingress_submissions_per_second": 180,
                "settled_submissions_per_second": 90,
            }))
            second.write_text(json.dumps({
                "failure_count": 0,
                "settled_failure_count": 0,
                "summary": {
                    "ingress": {"submissions_per_second": 220},
                },
                "settled_submissions_per_second": 110,
            }))

            result = run_deployment_verification.summarize_settled_benchmarks([first, second])

        self.assertEqual(result["ingress_throughput"]["min"], 180.0)
        self.assertEqual(result["ingress_throughput"]["median"], 200.0)
        self.assertEqual(result["ingress_throughput"]["max"], 220.0)
        self.assertEqual(result["settled_throughput"]["min"], 90.0)
        self.assertEqual(result["settled_throughput"]["median"], 100.0)
        self.assertEqual(result["settled_throughput"]["max"], 110.0)

    def test_summarize_settled_benchmarks_rejects_unexpected_failures(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settled.json"
            path.write_text(json.dumps({
                "failure_count": 0,
                "settled_failure_count": 1,
                "ingress_submissions_per_second": 180,
                "settled_submissions_per_second": 90,
            }))

            with self.assertRaisesRegex(RuntimeError, "unexpected failures"):
                run_deployment_verification.summarize_settled_benchmarks([path])

    def test_admin_diagnostics_require_validated_provider_proof(self):
        payloads = {
            "/v1/admin/diagnostics/runtime": self._hosted_runtime_payload(),
            "/v1/admin/diagnostics/media-smoke": {"ok": True, "gpu_used": True},
            "/v1/admin/diagnostics/provider-smoke": {
                "ok": True,
                "request_reached_provider": True,
                "normalized_result_returned": True,
                "provider_response_validated": True,
            },
            "/v1/admin/diagnostics/end-to-end-smoke": {
                "ok": True,
                "gpu_used": True,
                "provider_smoke": {
                    "ok": True,
                    "request_reached_provider": True,
                    "normalized_result_returned": True,
                    "provider_response_validated": True,
                },
            },
        }

        def fake_urlopen(req, timeout=None):
            path = req.full_url.replace("https://hearthlight.example.com/api", "")
            return _Response(payloads[path])

        with patch.object(run_deployment_verification.request, "urlopen", side_effect=fake_urlopen):
            result = run_deployment_verification.run_admin_diagnostics(
                "https://hearthlight.example.com/api",
                admin_prefix="/v1/admin/diagnostics",
                api_key=None,
                provider_key="openai",
                timeout_seconds=3,
            )

        self.assertTrue(result["provider_smoke"]["provider_response_validated"])

        payloads["/v1/admin/diagnostics/provider-smoke"] = {
            "ok": True,
            "request_reached_provider": True,
            "normalized_result_returned": False,
            "provider_response_validated": False,
        }
        with patch.object(run_deployment_verification.request, "urlopen", side_effect=fake_urlopen):
            with self.assertRaisesRegex(RuntimeError, "normalized provider result"):
                run_deployment_verification.run_admin_diagnostics(
                    "https://hearthlight.example.com/api",
                    admin_prefix="/v1/admin/diagnostics",
                    api_key=None,
                    provider_key="openai",
                    timeout_seconds=3,
                )

    def test_admin_diagnostics_require_reference_runtime_profile(self):
        runtime = self._hosted_runtime_payload()
        runtime["runtime_profile"]["database"]["postgres_host"] = "db"

        with self.assertRaisesRegex(RuntimeError, "runtime_profile.database.postgres_host"):
            run_deployment_verification.validate_runtime_profile(runtime)

        relaxed = run_deployment_verification.validate_runtime_profile(runtime, strict=False)
        self.assertFalse(relaxed["strict"])

    def test_ingress_contract_check_rejects_invalid_key_and_reads_back_submission(self):
        calls = []

        def fake_urlopen(req, timeout=None):
            calls.append((req.full_url, req.get_method(), req.get_header("Authorization"), req.data))
            body = json.loads(req.data.decode("utf-8")) if req.data else {}
            if req.get_method() == "POST" and "invalid-secret" in str(req.get_header("Authorization")):
                raise error.HTTPError(
                    req.full_url,
                    401,
                    "Unauthorized",
                    hdrs=None,
                    fp=io.BytesIO(b'{"detail":"invalid ingress client key"}'),
                )
            if req.get_method() == "GET" and req.full_url.endswith("/assets/0"):
                return _BinaryResponse(run_deployment_verification.INGRESS_SMOKE_ASSET_BYTES)
            if req.get_method() == "POST":
                return _Response(
                    {
                        "submission_id": "sub-test",
                        "status": "completed",
                        "prompt_text": body["prompt_text"],
                        "expected_results_text": body["expected_results_text"],
                        "provider_status": "skipped",
                        "processed_bucket": "640x480",
                        "token_units_final": 1,
                        "assets": [{"object_key": "submissions/sub-test/attachment-1.bin"}],
                    }
                )
            return _Response(
                {
                    "submission_id": "sub-test",
                    "status": "completed",
                    "prompt_text": "Return compact JSON for a Hearthlight deployment verifier ingress smoke.",
                    "expected_results_text": "Return title, category, score, and reasoning.",
                    "provider_status": "skipped",
                    "processed_bucket": "640x480",
                    "token_units_final": 1,
                    "assets": [{"object_key": "submissions/sub-test/attachment-1.bin"}],
                }
            )

        with patch.object(run_deployment_verification.request, "urlopen", side_effect=fake_urlopen):
            result = run_deployment_verification.run_ingress_contract_check(
                "https://hearthlight.example.com/api",
                ingress_endpoint="/v1/hearthlight/anomaly-submissions",
                client_key="valid-secret",
                invalid_client_key="invalid-secret",
                timeout_seconds=3,
            )

        self.assertEqual(result["invalid_key_rejection"]["http_status"], 401)
        self.assertEqual(result["valid_submission"]["submission_id"], "sub-test")
        self.assertEqual(result["valid_submission"]["provider_status"], "skipped")
        self.assertEqual(result["valid_submission"]["asset_count"], 1)
        self.assertEqual(result["valid_submission"]["asset_readback"], "passed")
        self.assertTrue(any(call[2] == "Bearer valid-secret" for call in calls))

    def test_ingress_contract_check_fails_when_invalid_key_is_accepted(self):
        with patch.object(
            run_deployment_verification.request,
            "urlopen",
            return_value=_Response({"submission_id": "bad", "status": "completed"}),
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid ingress client key was accepted"):
                run_deployment_verification.run_ingress_contract_check(
                    "https://hearthlight.example.com/api",
                    ingress_endpoint="/v1/hearthlight/anomaly-submissions",
                    client_key="valid-secret",
                    invalid_client_key="invalid-secret",
                    timeout_seconds=3,
                )


if __name__ == "__main__":
    unittest.main()
