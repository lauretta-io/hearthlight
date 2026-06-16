#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import statistics
import sys
import time
from pathlib import Path
from urllib import error, request


DEFAULT_ENDPOINT = "/v1/hearthlight/anomaly-submissions"
DEFAULT_OUTPUT_DIR = Path("shared/output/benchmarks")
DEFAULT_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class ClientCredential:
    label: str
    secret: str


@dataclass(frozen=True)
class RequestResult:
    client_label: str
    status_code: int | None
    latency_ms: float
    ok: bool
    error: str | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_client_credentials(values: list[str]) -> list[ClientCredential]:
    credentials: list[ClientCredential] = []
    for index, raw in enumerate(values, start=1):
        value = str(raw or "").strip()
        if not value:
            raise ValueError("client key values must be non-empty")
        if "=" in value:
            label, secret = value.split("=", 1)
            label = label.strip()
            secret = secret.strip()
            if not label or not secret:
                raise ValueError("client key entries using label=secret require both values")
        else:
            label = f"client-{index}"
            secret = value
        credentials.append(ClientCredential(label=label, secret=secret))
    labels = [credential.label for credential in credentials]
    if len(labels) != len(set(labels)):
        raise ValueError("client key labels must be unique")
    return credentials


def load_payload(args: argparse.Namespace) -> dict:
    if args.payload_file:
        payload = json.loads(args.payload_file.read_text())
    elif args.payload_json:
        payload = json.loads(args.payload_json)
    else:
        payload = {
            "camera_id": args.camera_id,
            "user_id": args.user_id,
            "prompt_template": args.prompt,
            "expected_results_text": args.expected_results_text,
            "image_attachments": [],
            "metadata": {
                "source": "queue-ingress-benchmark",
                "queue_only": True,
            },
        }
    if not isinstance(payload, dict):
        raise ValueError("benchmark payload must be a JSON object")
    return payload


def build_auth_headers(
    credential: ClientCredential,
    *,
    auth_header: str,
    auth_scheme: str,
) -> dict[str, str]:
    if auth_scheme == "bearer":
        auth_value = f"Bearer {credential.secret}"
    else:
        auth_value = credential.secret
    return {
        "Content-Type": "application/json",
        auth_header: auth_value,
    }


def send_submission(
    *,
    url: str,
    payload: dict,
    credential: ClientCredential,
    auth_header: str,
    auth_scheme: str,
    timeout_seconds: float,
) -> RequestResult:
    headers = build_auth_headers(
        credential,
        auth_header=auth_header,
        auth_scheme=auth_scheme,
    )
    started = time.perf_counter()
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            response.read()
            status_code = int(response.status)
        latency_ms = (time.perf_counter() - started) * 1000.0
        return RequestResult(
            client_label=credential.label,
            status_code=status_code,
            latency_ms=latency_ms,
            ok=200 <= status_code < 300,
        )
    except error.HTTPError as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            exc.read(1024)
        except Exception:
            pass
        return RequestResult(
            client_label=credential.label,
            status_code=exc.code,
            latency_ms=latency_ms,
            ok=False,
            error=f"HTTP {exc.code}",
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        return RequestResult(
            client_label=credential.label,
            status_code=None,
            latency_ms=latency_ms,
            ok=False,
            error=type(exc).__name__,
        )


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * pct
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summarize_latency(results: list[RequestResult]) -> dict[str, float | None]:
    latencies = [result.latency_ms for result in results]
    return {
        "min": min(latencies) if latencies else None,
        "median": statistics.median(latencies) if latencies else None,
        "p95": percentile(latencies, 0.95),
        "max": max(latencies) if latencies else None,
    }


def summarize_client_results(results: list[RequestResult], client_labels: list[str]) -> list[dict]:
    output: list[dict] = []
    for label in client_labels:
        client_results = [result for result in results if result.client_label == label]
        status_codes = sorted(
            {
                str(result.status_code)
                for result in client_results
                if result.status_code is not None
            }
        )
        errors = sorted({result.error for result in client_results if result.error})
        output.append(
            {
                "client_key": label,
                "request_count": len(client_results),
                "success_count": sum(1 for result in client_results if result.ok),
                "failure_count": sum(1 for result in client_results if not result.ok),
                "status_codes": status_codes,
                "errors": errors,
                "latency_ms": summarize_latency(client_results),
            }
        )
    return output


def build_report(
    *,
    base_url: str,
    endpoint: str,
    auth_header: str,
    auth_scheme: str,
    repeat_results: list[dict],
    started_at: str,
    finished_at: str,
) -> dict:
    throughput_samples = [
        float(run["submissions_per_second"])
        for run in repeat_results
        if isinstance(run.get("submissions_per_second"), (int, float))
    ]
    client_labels = sorted(
        {
            label
            for run in repeat_results
            for label in run.get("client_keys", [])
            if label
        }
    )
    return {
        "benchmark_type": "queue_only_ingress",
        "base_url": base_url.rstrip("/"),
        "endpoint": endpoint,
        "started_at": started_at,
        "finished_at": finished_at,
        "auth": {
            "header": auth_header,
            "scheme": auth_scheme,
            "secrets_redacted": True,
        },
        "client_keys": client_labels,
        "runs": repeat_results,
        "summary": {
            "repeat_count": len(repeat_results),
            "client_key_count": len(client_labels),
            "request_count": sum(int(run.get("request_count", 0)) for run in repeat_results),
            "success_count": sum(int(run.get("success_count", 0)) for run in repeat_results),
            "failure_count": sum(int(run.get("failure_count", 0)) for run in repeat_results),
            "throughput": {
                "min": min(throughput_samples) if throughput_samples else None,
                "median": statistics.median(throughput_samples) if throughput_samples else None,
                "max": max(throughput_samples) if throughput_samples else None,
            },
        },
    }


def run_repeat(
    *,
    repeat_index: int,
    url: str,
    payload: dict,
    credentials: list[ClientCredential],
    requests_per_repeat: int,
    concurrency: int,
    auth_header: str,
    auth_scheme: str,
    timeout_seconds: float,
) -> dict:
    started_at = utc_now_iso()
    started = time.perf_counter()
    results: list[RequestResult] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = []
        for index in range(requests_per_repeat):
            credential = credentials[index % len(credentials)]
            futures.append(
                executor.submit(
                    send_submission,
                    url=url,
                    payload=payload,
                    credential=credential,
                    auth_header=auth_header,
                    auth_scheme=auth_scheme,
                    timeout_seconds=timeout_seconds,
                )
            )
        for future in as_completed(futures):
            results.append(future.result())
    elapsed_seconds = max(time.perf_counter() - started, 0.000001)
    success_count = sum(1 for result in results if result.ok)
    failure_count = len(results) - success_count
    client_labels = [credential.label for credential in credentials]
    return {
        "repeat_index": repeat_index,
        "started_at": started_at,
        "finished_at": utc_now_iso(),
        "elapsed_seconds": elapsed_seconds,
        "request_count": len(results),
        "success_count": success_count,
        "failure_count": failure_count,
        "submissions_per_second": success_count / elapsed_seconds,
        "client_keys": client_labels,
        "client_results": summarize_client_results(results, client_labels),
        "latency_ms": summarize_latency(results),
    }


def default_output_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_OUTPUT_DIR / f"queue_only_{timestamp}.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a queue-only Hearthlight ingress benchmark and emit verifier-compatible JSON."
    )
    parser.add_argument("--base-url", required=True, help="API base URL, for example https://host.example/api")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument(
        "--client-key",
        action="append",
        required=True,
        help="Client key secret, or label=secret. Reports include labels only.",
    )
    parser.add_argument("--auth-header", default="X-API-Key")
    parser.add_argument("--auth-scheme", choices=["raw", "bearer"], default="raw")
    parser.add_argument("--requests-per-repeat", type=int, default=1000)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=64)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--payload-file", type=Path)
    parser.add_argument("--payload-json")
    parser.add_argument("--camera-id", type=int, default=1)
    parser.add_argument("--user-id", default="queue-benchmark-user")
    parser.add_argument("--prompt", default="Return a compact anomaly JSON result for this frame.")
    parser.add_argument("--expected-results-text", default="Return title, category, score, reasoning, visible_items, and visible_activities.")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.requests_per_repeat <= 0:
        raise SystemExit("--requests-per-repeat must be greater than zero")
    if args.repeat <= 0:
        raise SystemExit("--repeat must be greater than zero")
    if args.concurrency <= 0:
        raise SystemExit("--concurrency must be greater than zero")
    credentials = parse_client_credentials(args.client_key)
    payload = load_payload(args)
    endpoint = args.endpoint if args.endpoint.startswith("/") else f"/{args.endpoint}"
    base_url = args.base_url.rstrip("/")
    url = f"{base_url}{endpoint}"
    started_at = utc_now_iso()
    repeat_results = []
    for repeat_index in range(1, args.repeat + 1):
        repeat_result = run_repeat(
            repeat_index=repeat_index,
            url=url,
            payload=payload,
            credentials=credentials,
            requests_per_repeat=args.requests_per_repeat,
            concurrency=args.concurrency,
            auth_header=args.auth_header,
            auth_scheme=args.auth_scheme,
            timeout_seconds=args.timeout_seconds,
        )
        repeat_results.append(repeat_result)
        print(
            "repeat {repeat_index}: {success}/{total} ok, {rate:.2f}/sec".format(
                repeat_index=repeat_index,
                success=repeat_result["success_count"],
                total=repeat_result["request_count"],
                rate=repeat_result["submissions_per_second"],
            ),
            file=sys.stderr,
        )
    report = build_report(
        base_url=base_url,
        endpoint=endpoint,
        auth_header=args.auth_header,
        auth_scheme=args.auth_scheme,
        repeat_results=repeat_results,
        started_at=started_at,
        finished_at=utc_now_iso(),
    )
    output_path = args.output or default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(str(output_path))
    return 0 if report["summary"]["failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
