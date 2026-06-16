import json
import unittest

from scripts import benchmark_settled_ingress


class BenchmarkSettledIngressTests(unittest.TestCase):
    def test_extract_submission_id_supports_nested_fields(self):
        payload = {"data": {"submission": {"id": "sub-123"}}}

        self.assertEqual(
            benchmark_settled_ingress.extract_submission_id(
                payload,
                ["submission_id", "data.submission.id"],
            ),
            "sub-123",
        )

    def test_build_status_url_escapes_submission_id(self):
        url = benchmark_settled_ingress.build_status_url(
            "https://hearthlight.example.com/api/",
            "/v1/submissions/{submission_id}/status",
            "sub 1/2",
        )

        self.assertEqual(
            url,
            "https://hearthlight.example.com/api/v1/submissions/sub%201%2F2/status",
        )

    def test_extract_status_normalizes_status_fields(self):
        payload = {"result": {"state": " Completed "}}

        self.assertEqual(
            benchmark_settled_ingress.extract_status(payload, ["status", "result.state"]),
            "completed",
        )

    def test_build_report_records_ingress_and_settled_metrics_without_secrets(self):
        submitted = [
            benchmark_settled_ingress.SubmittedItem(
                client_label="client-a",
                submission_id="sub-a",
                status_code=202,
                latency_ms=10.0,
                ok=True,
                submitted_at="2026-06-15T00:00:00Z",
            ),
            benchmark_settled_ingress.SubmittedItem(
                client_label="client-b",
                submission_id="sub-b",
                status_code=202,
                latency_ms=20.0,
                ok=True,
                submitted_at="2026-06-15T00:00:00Z",
            ),
        ]
        settled = [
            benchmark_settled_ingress.SettledItem(
                client_label="client-a",
                submission_id="sub-a",
                ok=True,
                terminal=True,
                status="completed",
                settle_latency_ms=100.0,
                poll_count=2,
            ),
            benchmark_settled_ingress.SettledItem(
                client_label="client-b",
                submission_id="sub-b",
                ok=True,
                terminal=True,
                status="completed",
                settle_latency_ms=200.0,
                poll_count=3,
            ),
        ]

        report = benchmark_settled_ingress.build_report(
            base_url="https://hearthlight.example.com/api/",
            endpoint="/v1/hearthlight/anomaly-submissions",
            status_endpoint_template="/v1/hearthlight/anomaly-submissions/{submission_id}",
            auth_header="Authorization",
            auth_scheme="bearer",
            client_labels=["client-a", "client-b"],
            submitted=submitted,
            settled=settled,
            started_at="2026-06-15T00:00:00Z",
            finished_at="2026-06-15T00:00:01Z",
            elapsed_seconds=1.0,
        )
        encoded = json.dumps(report)

        self.assertEqual(report["benchmark_type"], "settled_end_to_end")
        self.assertEqual(report["ingress_submissions_per_second"], 2.0)
        self.assertEqual(report["settled_submissions_per_second"], 2.0)
        self.assertEqual(report["summary"]["settled"]["latency_ms"]["median"], 150.0)
        self.assertEqual(report["summary"]["settled"]["settled_count"], 2)
        self.assertEqual(report["summary"]["settled"]["failed_count"], 0)
        self.assertNotIn("secret-a", encoded)
        self.assertNotIn("secret-b", encoded)


if __name__ == "__main__":
    unittest.main()
