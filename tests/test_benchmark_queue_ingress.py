import json
import unittest

from scripts import benchmark_queue_ingress


class BenchmarkQueueIngressTests(unittest.TestCase):
    def test_parse_client_credentials_uses_labels_without_exposing_secret_as_label(self):
        credentials = benchmark_queue_ingress.parse_client_credentials([
            "client-a=secret-a",
            "secret-b",
        ])

        self.assertEqual(credentials[0].label, "client-a")
        self.assertEqual(credentials[0].secret, "secret-a")
        self.assertEqual(credentials[1].label, "client-2")
        self.assertEqual(credentials[1].secret, "secret-b")

    def test_parse_client_credentials_rejects_duplicate_labels(self):
        with self.assertRaisesRegex(ValueError, "labels must be unique"):
            benchmark_queue_ingress.parse_client_credentials([
                "client-a=secret-a",
                "client-a=secret-b",
            ])

    def test_build_auth_headers_supports_bearer_auth(self):
        credential = benchmark_queue_ingress.ClientCredential(label="client-a", secret="secret-a")

        headers = benchmark_queue_ingress.build_auth_headers(
            credential,
            auth_header="Authorization",
            auth_scheme="bearer",
        )

        self.assertEqual(headers["Authorization"], "Bearer secret-a")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_build_report_is_verifier_compatible_and_redacts_secrets(self):
        repeat_results = [
            {
                "repeat_index": 1,
                "request_count": 100,
                "success_count": 100,
                "failure_count": 0,
                "submissions_per_second": 210.0,
                "client_keys": ["client-a", "client-b"],
                "client_results": [
                    {
                        "client_key": "client-a",
                        "request_count": 50,
                        "success_count": 50,
                        "failure_count": 0,
                    },
                    {
                        "client_key": "client-b",
                        "request_count": 50,
                        "success_count": 50,
                        "failure_count": 0,
                    },
                ],
            },
            {
                "repeat_index": 2,
                "request_count": 100,
                "success_count": 100,
                "failure_count": 0,
                "submissions_per_second": 230.0,
                "client_keys": ["client-a", "client-b"],
                "client_results": [],
            },
        ]

        report = benchmark_queue_ingress.build_report(
            base_url="https://hearthlight.example.com/api/",
            endpoint="/v1/hearthlight/anomaly-submissions",
            auth_header="Authorization",
            auth_scheme="bearer",
            repeat_results=repeat_results,
            started_at="2026-06-15T00:00:00Z",
            finished_at="2026-06-15T00:01:00Z",
        )
        encoded = json.dumps(report)

        self.assertEqual(report["benchmark_type"], "queue_only_ingress")
        self.assertEqual(report["client_keys"], ["client-a", "client-b"])
        self.assertEqual(report["summary"]["throughput"]["median"], 220.0)
        self.assertEqual(report["summary"]["client_key_count"], 2)
        self.assertNotIn("secret-a", encoded)
        self.assertNotIn("secret-b", encoded)

    def test_summarize_client_results_does_not_emit_per_client_throughput_fields(self):
        results = [
            benchmark_queue_ingress.RequestResult(
                client_label="client-a",
                status_code=202,
                latency_ms=10.0,
                ok=True,
            ),
            benchmark_queue_ingress.RequestResult(
                client_label="client-b",
                status_code=202,
                latency_ms=20.0,
                ok=True,
            ),
        ]

        client_results = benchmark_queue_ingress.summarize_client_results(
            results,
            ["client-a", "client-b"],
        )
        encoded = json.dumps(client_results)

        self.assertIn("client-a", encoded)
        self.assertNotIn("submissions_per_second", encoded)
        self.assertNotIn("requests_per_second", encoded)


if __name__ == "__main__":
    unittest.main()
