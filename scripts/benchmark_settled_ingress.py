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
from urllib import error, parse, request

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark_queue_ingress import (
    ClientCredential,
    DEFAULT_ENDPOINT,
    DEFAULT_OUTPUT_DIR,
    build_auth_headers,
    load_payload,
    parse_client_credentials,
    percentile,
    summarize_latency,
)


DEFAULT_STATUS_ENDPOINT_TEMPLATE = "/v1/hearthlight/anomaly-submissions/{submission_id}"
DEFAULT_POLL_INTERVAL_SECONDS = 0.25
DEFAULT_SETTLE_TIMEOUT_SECONDS = 120.0
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_TERMINAL_STATUSES = {"settled", "completed", "complete", "succeeded", "success", "done", "failed", "error"}
DEFAULT_SUCCESS_STATUSES = {"settled", "completed", "complete", "succeeded", "success", "done"}
DEFAULT_FAILURE_STATUSES = {"failed", "error"}
DEFAULT_SUBMISSION_ID_FIELDS = (
    "submission_id",
    "id",
    "job_id",
    "request_id",
    "event_id",
)
DEFAULT_STATUS_FIELDS = ("status", "state", "phase")


@dataclass(frozen=True)
class SubmittedItem:
    client_label: str
    submission_id: str | None
    status_code: int | None
    latency_ms: float
    ok: bool
    submitted_at: str
    error: str | None = None


@dataclass(frozen=True)
class SettledItem:
    client_label: str
    submission_id: str | None
    ok: bool
    terminal: bool
    status: str | None
    settle_latency_ms: float | None
    poll_count: int
    error: str | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def nested_get(payload, dotted_path: str):
    current = payload
    for part in dotted_path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def extract_submission_id(payload, fields: list[str]) -> str | None:
    if not isinstance(payload, dict):
        return None
    for field in fields:
        value = nested_get(payload, field)
        if value:
            return str(value)
    return None


def extract_status(payload, fields: list[str]) -> str | None:
    if not isinstance(payload, dict):
        return None
    for field in fields:
        value = nested_get(payload, field)
        if value:
            return str(value).strip().lower()
    return None


def submit_once(
    *,
    url: str,
    payload: dict,
    credential: ClientCredential,
    auth_header: str,
    auth_scheme: str,
    id_fields: list[str],
    timeout_seconds: float,
) -> SubmittedItem:
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
    submitted_at = utc_now_iso()
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            status_code = int(response.status)
        body = json.loads(raw or "{}")
        latency_ms = (time.perf_counter() - started) * 1000.0
        return SubmittedItem(
            client_label=credential.label,
            submission_id=extract_submission_id(body, id_fields),
            status_code=status_code,
            latency_ms=latency_ms,
            ok=200 <= status_code < 300,
            submitted_at=submitted_at,
        )
    except error.HTTPError as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            exc.read(1024)
        except Exception:
            pass
        return SubmittedItem(
            client_label=credential.label,
            submission_id=None,
            status_code=exc.code,
            latency_ms=latency_ms,
            ok=False,
            submitted_at=submitted_at,
            error=f"HTTP {exc.code}",
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        return SubmittedItem(
            client_label=credential.label,
            submission_id=None,
            status_code=None,
            latency_ms=latency_ms,
            ok=False,
            submitted_at=submitted_at,
            error=type(exc).__name__,
        )


def build_status_url(base_url: str, template: str, submission_id: str) -> str:
    endpoint = template.format(submission_id=parse.quote(submission_id, safe=""))
    if not endpoint.startswith("/"):
        endpoint = f"/{endpoint}"
    return f"{base_url.rstrip('/')}{endpoint}"


def poll_settle(
    *,
    base_url: str,
    status_endpoint_template: str,
    submitted: SubmittedItem,
    credential: ClientCredential,
    auth_header: str,
    auth_scheme: str,
    status_fields: list[str],
    success_statuses: set[str],
    failure_statuses: set[str],
    terminal_statuses: set[str],
    poll_interval_seconds: float,
    settle_timeout_seconds: float,
    timeout_seconds: float,
) -> SettledItem:
    if not submitted.ok:
        return SettledItem(
            client_label=submitted.client_label,
            submission_id=submitted.submission_id,
            ok=False,
            terminal=True,
            status="submit_failed",
            settle_latency_ms=None,
            poll_count=0,
            error=submitted.error or "submit_failed",
        )
    if not submitted.submission_id:
        return SettledItem(
            client_label=submitted.client_label,
            submission_id=None,
            ok=False,
            terminal=True,
            status="missing_submission_id",
            settle_latency_ms=None,
            poll_count=0,
            error="submit response did not include a submission id",
        )
    headers = build_auth_headers(
        credential,
        auth_header=auth_header,
        auth_scheme=auth_scheme,
    )
    status_url = build_status_url(base_url, status_endpoint_template, submitted.submission_id)
    deadline = time.perf_counter() + settle_timeout_seconds
    poll_count = 0
    started = time.perf_counter()
    last_status: str | None = None
    last_error: str | None = None
    while time.perf_counter() <= deadline:
        poll_count += 1
        req = request.Request(status_url, headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8")
            payload = json.loads(raw or "{}")
            status = extract_status(payload, status_fields)
            last_status = status or last_status
            if status in terminal_statuses:
                settle_latency_ms = (time.perf_counter() - started) * 1000.0
                return SettledItem(
                    client_label=submitted.client_label,
                    submission_id=submitted.submission_id,
                    ok=status in success_statuses and status not in failure_statuses,
                    terminal=True,
                    status=status,
                    settle_latency_ms=settle_latency_ms,
                    poll_count=poll_count,
                    error=None if status in success_statuses else status,
                )
        except error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            try:
                exc.read(1024)
            except Exception:
                pass
        except Exception as exc:
            last_error = type(exc).__name__
        time.sleep(poll_interval_seconds)
    return SettledItem(
        client_label=submitted.client_label,
        submission_id=submitted.submission_id,
        ok=False,
        terminal=False,
        status=last_status or "timeout",
        settle_latency_ms=None,
        poll_count=poll_count,
        error=last_error or "settle_timeout",
    )


def summarize_numeric(values: list[float]) -> dict[str, float | None]:
    return {
        "min": min(values) if values else None,
        "median": statistics.median(values) if values else None,
        "p95": percentile(values, 0.95),
        "max": max(values) if values else None,
    }


def summarize_settled_items(items: list[SettledItem]) -> dict:
    latencies = [
        item.settle_latency_ms
        for item in items
        if item.settle_latency_ms is not None
    ]
    return {
        "settled_count": sum(1 for item in items if item.ok),
        "failed_count": sum(1 for item in items if not item.ok),
        "terminal_count": sum(1 for item in items if item.terminal),
        "latency_ms": summarize_numeric(latencies),
        "poll_count": {
            "min": min((item.poll_count for item in items), default=None),
            "median": statistics.median([item.poll_count for item in items]) if items else None,
            "max": max((item.poll_count for item in items), default=None),
        },
    }


def build_report(
    *,
    base_url: str,
    endpoint: str,
    status_endpoint_template: str,
    auth_header: str,
    auth_scheme: str,
    client_labels: list[str],
    submitted: list[SubmittedItem],
    settled: list[SettledItem],
    started_at: str,
    finished_at: str,
    elapsed_seconds: float,
) -> dict:
    success_count = sum(1 for item in submitted if item.ok)
    settled_success_count = sum(1 for item in settled if item.ok)
    ingress_rate = success_count / max(elapsed_seconds, 0.000001)
    settled_rate = settled_success_count / max(elapsed_seconds, 0.000001)
    client_results = []
    for label in client_labels:
        client_submitted = [item for item in submitted if item.client_label == label]
        client_settled = [item for item in settled if item.client_label == label]
        client_results.append(
            {
                "client_key": label,
                "request_count": len(client_submitted),
                "success_count": sum(1 for item in client_submitted if item.ok),
                "failure_count": sum(1 for item in client_submitted if not item.ok),
                "settled_success_count": sum(1 for item in client_settled if item.ok),
                "settled_failure_count": sum(1 for item in client_settled if not item.ok),
                "ingress_latency_ms": summarize_numeric([item.latency_ms for item in client_submitted]),
                "settle_latency_ms": summarize_numeric([
                    item.settle_latency_ms
                    for item in client_settled
                    if item.settle_latency_ms is not None
                ]),
            }
        )
    return {
        "benchmark_type": "settled_end_to_end",
        "base_url": base_url.rstrip("/"),
        "endpoint": endpoint,
        "status_endpoint_template": status_endpoint_template,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": elapsed_seconds,
        "auth": {
            "header": auth_header,
            "scheme": auth_scheme,
            "secrets_redacted": True,
        },
        "client_keys": client_labels,
        "request_count": len(submitted),
        "success_count": success_count,
        "failure_count": len(submitted) - success_count,
        "settled_success_count": settled_success_count,
        "settled_failure_count": len(settled) - settled_success_count,
        "ingress_submissions_per_second": ingress_rate,
        "settled_submissions_per_second": settled_rate,
        "summary": {
            "ingress": {
                "submissions_per_second": ingress_rate,
                "latency_ms": summarize_numeric([item.latency_ms for item in submitted]),
            },
            "settled": summarize_settled_items(settled),
        },
        "client_results": client_results,
        "settled_results": [
            {
                "client_key": item.client_label,
                "submission_id_present": bool(item.submission_id),
                "ok": item.ok,
                "terminal": item.terminal,
                "status": item.status,
                "settle_latency_ms": item.settle_latency_ms,
                "poll_count": item.poll_count,
                "error": item.error,
            }
            for item in settled
        ],
    }


def parse_csv_set(value: str, defaults: set[str]) -> set[str]:
    if not value:
        return set(defaults)
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def parse_csv_list(value: str, defaults: tuple[str, ...]) -> list[str]:
    if not value:
        return list(defaults)
    return [item.strip() for item in value.split(",") if item.strip()]


def default_output_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return DEFAULT_OUTPUT_DIR / f"settled_{timestamp}.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a settled end-to-end Hearthlight benchmark and emit deployment verifier JSON."
    )
    parser.add_argument("--base-url", required=True, help="API base URL, for example https://host.example/api")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--status-endpoint-template", default=DEFAULT_STATUS_ENDPOINT_TEMPLATE)
    parser.add_argument(
        "--client-key",
        action="append",
        required=True,
        help="Client key secret, or label=secret. Reports include labels only.",
    )
    parser.add_argument("--auth-header", default="X-API-Key")
    parser.add_argument("--auth-scheme", choices=["raw", "bearer"], default="raw")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=16)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--settle-timeout-seconds", type=float, default=DEFAULT_SETTLE_TIMEOUT_SECONDS)
    parser.add_argument("--poll-interval-seconds", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--submission-id-fields", default=",".join(DEFAULT_SUBMISSION_ID_FIELDS))
    parser.add_argument("--status-fields", default=",".join(DEFAULT_STATUS_FIELDS))
    parser.add_argument("--success-statuses", default=",".join(sorted(DEFAULT_SUCCESS_STATUSES)))
    parser.add_argument("--failure-statuses", default=",".join(sorted(DEFAULT_FAILURE_STATUSES)))
    parser.add_argument("--terminal-statuses", default=",".join(sorted(DEFAULT_TERMINAL_STATUSES)))
    parser.add_argument("--payload-file", type=Path)
    parser.add_argument("--payload-json")
    parser.add_argument("--camera-id", type=int, default=1)
    parser.add_argument("--user-id", default="settled-benchmark-user")
    parser.add_argument("--prompt", default="Return a compact anomaly JSON result for this frame.")
    parser.add_argument("--expected-results-text", default="Return title, category, score, reasoning, visible_items, and visible_activities.")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.requests <= 0:
        raise SystemExit("--requests must be greater than zero")
    if args.concurrency <= 0:
        raise SystemExit("--concurrency must be greater than zero")
    credentials = parse_client_credentials(args.client_key)
    payload = load_payload(args)
    endpoint = args.endpoint if args.endpoint.startswith("/") else f"/{args.endpoint}"
    base_url = args.base_url.rstrip("/")
    submit_url = f"{base_url}{endpoint}"
    id_fields = parse_csv_list(args.submission_id_fields, DEFAULT_SUBMISSION_ID_FIELDS)
    status_fields = parse_csv_list(args.status_fields, DEFAULT_STATUS_FIELDS)
    success_statuses = parse_csv_set(args.success_statuses, DEFAULT_SUCCESS_STATUSES)
    failure_statuses = parse_csv_set(args.failure_statuses, DEFAULT_FAILURE_STATUSES)
    terminal_statuses = parse_csv_set(args.terminal_statuses, DEFAULT_TERMINAL_STATUSES)
    terminal_statuses.update(success_statuses)
    terminal_statuses.update(failure_statuses)

    started_at = utc_now_iso()
    started = time.perf_counter()
    submitted: list[SubmittedItem] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = []
        for index in range(args.requests):
            credential = credentials[index % len(credentials)]
            futures.append(
                executor.submit(
                    submit_once,
                    url=submit_url,
                    payload=payload,
                    credential=credential,
                    auth_header=args.auth_header,
                    auth_scheme=args.auth_scheme,
                    id_fields=id_fields,
                    timeout_seconds=args.timeout_seconds,
                )
            )
        for future in as_completed(futures):
            submitted.append(future.result())

    credentials_by_label = {credential.label: credential for credential in credentials}
    settled: list[SettledItem] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(
                poll_settle,
                base_url=base_url,
                status_endpoint_template=args.status_endpoint_template,
                submitted=item,
                credential=credentials_by_label[item.client_label],
                auth_header=args.auth_header,
                auth_scheme=args.auth_scheme,
                status_fields=status_fields,
                success_statuses=success_statuses,
                failure_statuses=failure_statuses,
                terminal_statuses=terminal_statuses,
                poll_interval_seconds=args.poll_interval_seconds,
                settle_timeout_seconds=args.settle_timeout_seconds,
                timeout_seconds=args.timeout_seconds,
            )
            for item in submitted
        ]
        for future in as_completed(futures):
            settled.append(future.result())

    elapsed_seconds = max(time.perf_counter() - started, 0.000001)
    client_labels = [credential.label for credential in credentials]
    report = build_report(
        base_url=base_url,
        endpoint=endpoint,
        status_endpoint_template=args.status_endpoint_template,
        auth_header=args.auth_header,
        auth_scheme=args.auth_scheme,
        client_labels=client_labels,
        submitted=submitted,
        settled=settled,
        started_at=started_at,
        finished_at=utc_now_iso(),
        elapsed_seconds=elapsed_seconds,
    )
    output_path = args.output or default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(str(output_path))
    print(
        "settled {settled}/{total}, ingress {ingress:.2f}/sec, settled {settled_rate:.2f}/sec".format(
            settled=report["settled_success_count"],
            total=report["request_count"],
            ingress=report["ingress_submissions_per_second"],
            settled_rate=report["settled_submissions_per_second"],
        ),
        file=sys.stderr,
    )
    return 0 if report["failure_count"] == 0 and report["settled_failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
