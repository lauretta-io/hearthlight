#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
from json import JSONDecodeError
import json
import statistics
import sys
import time
from pathlib import Path
from urllib import error, request


DEFAULT_ADMIN_PREFIX = "/v1/admin/diagnostics"
DEFAULT_QUEUE_GATE = 200.0
DEFAULT_INGRESS_ENDPOINT = "/v1/hearthlight/anomaly-submissions"
INGRESS_SMOKE_ASSET_BYTES = b"hearthlight-verifier-frame"
EXPECTED_RUNTIME_PROFILE = {
    ("api", "api_web_concurrency"): "12",
    ("api", "api_client_cache_ttl_seconds"): "15",
    ("api", "local_stack"): False,
    ("database", "postgres_host"): "pgbouncer",
    ("database", "postgres_port"): "6432",
    ("database", "db_pool_size"): "4",
    ("database", "db_max_overflow"): "4",
    ("worker", "worker_runtime"): "docker",
    ("worker", "worker_concurrency"): "32",
    ("worker", "worker_poll_seconds"): "0.05",
    ("worker", "inline_inference_after_preprocess"): True,
    ("object_store", "backend"): "s3",
}


def build_headers(api_key: str | None, *, content_type: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def build_ingress_headers(client_key: str | None, *, content_type: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if client_key:
        headers["Authorization"] = f"Bearer {client_key}"
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def send_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload=None,
    api_key: str | None = None,
    timeout_seconds: float = 60.0,
):
    body = None
    headers = build_headers(api_key, content_type="application/json")
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        base_url.rstrip("/") + path,
        data=body,
        headers=headers,
        method=method,
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except JSONDecodeError as exc:
        raise RuntimeError(f"{path} did not return JSON; admin diagnostics may be missing") from exc


def send_ingress_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload=None,
    client_key: str | None = None,
    timeout_seconds: float = 60.0,
):
    body = None
    headers = build_ingress_headers(client_key, content_type="application/json")
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        base_url.rstrip("/") + path,
        data=body,
        headers=headers,
        method=method,
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except JSONDecodeError as exc:
        raise RuntimeError(f"{path} did not return JSON") from exc


def send_ingress_binary(
    base_url: str,
    path: str,
    *,
    client_key: str | None = None,
    timeout_seconds: float = 60.0,
) -> bytes:
    req = request.Request(
        base_url.rstrip("/") + path,
        headers=build_ingress_headers(client_key),
        method="GET",
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        return response.read()


def expect_ingress_invalid_key_rejected(
    base_url: str,
    *,
    ingress_endpoint: str,
    invalid_client_key: str,
    timeout_seconds: float,
) -> dict:
    payload = {
        "camera_id": 1,
        "user_id": "deployment-verifier-invalid",
        "prompt_text": "Reject this invalid-key deployment verifier submission.",
        "expected_results_text": "This should not be accepted.",
        "image_attachments": [],
        "metadata": {"source": "deployment-verifier", "queue_only": True},
    }
    try:
        send_ingress_json(
            base_url,
            ingress_endpoint,
            method="POST",
            payload=payload,
            client_key=invalid_client_key,
            timeout_seconds=timeout_seconds,
        )
    except error.HTTPError as exc:
        try:
            body = exc.read().decode(errors="replace")
            if exc.code != 401:
                raise RuntimeError(f"invalid ingress client key returned HTTP {exc.code}, expected 401: {body}") from exc
            return {"status": "passed", "http_status": exc.code}
        finally:
            exc.close()
    raise RuntimeError("invalid ingress client key was accepted")


def run_ingress_contract_check(
    base_url: str,
    *,
    ingress_endpoint: str,
    client_key: str,
    invalid_client_key: str | None,
    timeout_seconds: float,
) -> dict:
    endpoint = ingress_endpoint if ingress_endpoint.startswith("/") else f"/{ingress_endpoint}"
    results: dict[str, dict] = {}
    if invalid_client_key:
        results["invalid_key_rejection"] = expect_ingress_invalid_key_rejected(
            base_url,
            ingress_endpoint=endpoint,
            invalid_client_key=invalid_client_key,
            timeout_seconds=timeout_seconds,
        )
    payload = {
        "camera_id": 1,
        "user_id": "deployment-verifier",
        "prompt_text": "Return compact JSON for a Hearthlight deployment verifier ingress smoke.",
        "expected_results_text": "Return title, category, score, and reasoning.",
        "image_attachments": [
            {
                "media_type": "image/jpeg",
                "data_base64": base64.b64encode(INGRESS_SMOKE_ASSET_BYTES).decode("ascii"),
                "width": 640,
                "height": 480,
                "metadata": {"source": "deployment-verifier"},
            }
        ],
        "metadata": {"source": "deployment-verifier", "queue_only": True},
    }
    submitted = send_ingress_json(
        base_url,
        endpoint,
        method="POST",
        payload=payload,
        client_key=client_key,
        timeout_seconds=timeout_seconds,
    )
    expect(isinstance(submitted, dict), "ingress submission response must be an object")
    submission_id = str(submitted.get("submission_id") or "").strip()
    expect(submission_id, "ingress submission response missing submission_id")
    expect(submitted.get("status") in {"queued", "completed", "settled", "success"}, "ingress submission returned unexpected status")
    expect(submitted.get("prompt_text") == payload["prompt_text"], "ingress response did not preserve prompt_text")
    expect(submitted.get("expected_results_text") == payload["expected_results_text"], "ingress response did not preserve expected_results_text")
    expect(submitted.get("provider_status") in {"skipped", None}, "queue-only ingress smoke should skip provider dispatch")
    readback = send_ingress_json(
        base_url,
        f"{endpoint.rstrip('/')}/{submission_id}",
        client_key=client_key,
        timeout_seconds=timeout_seconds,
    )
    expect(readback.get("submission_id") == submission_id, "ingress readback submission_id mismatch")
    expect(readback.get("prompt_text") == payload["prompt_text"], "ingress readback did not preserve prompt_text")
    assets = readback.get("assets") or submitted.get("assets") or []
    expect(len(assets) >= 1, "ingress submission did not persist asset metadata")
    asset_bytes = send_ingress_binary(
        base_url,
        f"{endpoint.rstrip('/')}/{submission_id}/assets/0",
        client_key=client_key,
        timeout_seconds=timeout_seconds,
    )
    expect(asset_bytes == INGRESS_SMOKE_ASSET_BYTES, "ingress asset readback did not match submitted bytes")
    results["valid_submission"] = {
        "status": "passed",
        "submission_id": submission_id,
        "submission_status": submitted.get("status"),
        "provider_status": submitted.get("provider_status"),
        "processed_bucket": submitted.get("processed_bucket"),
        "token_units_final": submitted.get("token_units_final"),
        "asset_count": len(assets),
        "asset_readback": "passed",
    }
    return results


def read_json(path: Path):
    return json.loads(path.read_text())


def _as_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def extract_throughput_samples(payload) -> list[float]:
    samples: list[float] = []
    if isinstance(payload, list):
        for item in payload:
            samples.extend(extract_throughput_samples(item))
        return samples
    if not isinstance(payload, dict):
        return samples

    for key in (
        "submissions_per_second",
        "submission_rate_per_second",
        "ingress_submissions_per_second",
        "throughput_submissions_per_second",
        "requests_per_second",
        "rps",
    ):
        value = _as_number(payload.get(key))
        if value is not None:
            samples.append(value)

    for key in ("runs", "samples", "results", "benchmarks", "measurements"):
        nested = payload.get(key)
        if isinstance(nested, (list, dict)):
            samples.extend(extract_throughput_samples(nested))

    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        samples.extend(extract_throughput_samples(metrics))

    return samples


def extract_client_keys(payload) -> set[str]:
    keys: set[str] = set()
    if isinstance(payload, list):
        for item in payload:
            keys.update(extract_client_keys(item))
        return keys
    if not isinstance(payload, dict):
        return keys
    for key in ("client_key", "client_id", "api_key_id", "bucket_client_key"):
        value = payload.get(key)
        if value:
            keys.add(str(value))
    for key in ("client_keys", "clients"):
        value = payload.get(key)
        if isinstance(value, list):
            keys.update(str(item) for item in value if item)
    for key in ("runs", "samples", "results", "benchmarks", "measurements"):
        nested = payload.get(key)
        if isinstance(nested, (list, dict)):
            keys.update(extract_client_keys(nested))
    return keys


def summarize_samples(samples: list[float]) -> dict[str, float | int]:
    if not samples:
        raise ValueError("no throughput samples found")
    return {
        "count": len(samples),
        "min": min(samples),
        "median": statistics.median(samples),
        "max": max(samples),
    }


def _count_value(payload: dict, key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return 0
    return 0


def validate_queue_benchmarks(
    paths: list[Path],
    *,
    required_median: float,
    require_multiple_client_keys: bool,
) -> dict:
    samples: list[float] = []
    client_keys: set[str] = set()
    source_files: list[str] = []
    for path in paths:
        payload = read_json(path)
        source_files.append(str(path))
        samples.extend(extract_throughput_samples(payload))
        client_keys.update(extract_client_keys(payload))
    summary = summarize_samples(samples)
    if summary["median"] < required_median:
        raise RuntimeError(
            f"queue-only median {summary['median']:.2f}/sec is below required {required_median:.2f}/sec"
        )
    if require_multiple_client_keys and len(client_keys) < 2:
        raise RuntimeError("queue-only benchmark must include multiple client keys")
    return {
        "source_files": source_files,
        "throughput": summary,
        "client_key_count": len(client_keys),
    }


def summarize_settled_benchmarks(paths: list[Path]) -> dict | None:
    if not paths:
        return None
    ingress_samples: list[float] = []
    settled_samples: list[float] = []
    source_files: list[str] = []
    failures: list[str] = []
    for path in paths:
        payload = read_json(path)
        source_files.append(str(path))
        if not isinstance(payload, dict):
            raise RuntimeError(f"settled benchmark {path} must contain a JSON object")
        failure_count = _count_value(payload, "failure_count")
        settled_failure_count = _count_value(payload, "settled_failure_count")
        if failure_count or settled_failure_count:
            failures.append(
                f"{path}: failure_count={failure_count}, settled_failure_count={settled_failure_count}"
            )
        ingress_rate = _as_number(payload.get("ingress_submissions_per_second"))
        settled_rate = _as_number(payload.get("settled_submissions_per_second"))
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        ingress_summary = summary.get("ingress") if isinstance(summary.get("ingress"), dict) else {}
        if ingress_rate is None:
            ingress_rate = _as_number(ingress_summary.get("submissions_per_second"))
        if settled_rate is None:
            settled_rate = _as_number(summary.get("settled_submissions_per_second"))
        if ingress_rate is not None:
            ingress_samples.append(ingress_rate)
        if settled_rate is not None:
            settled_samples.append(settled_rate)
    if failures:
        raise RuntimeError("settled benchmark reported unexpected failures: " + "; ".join(failures))
    if not ingress_samples:
        raise RuntimeError("settled benchmark JSON missing ingress throughput samples")
    if not settled_samples:
        raise RuntimeError("settled benchmark JSON missing settled throughput samples")
    return {
        "source_files": source_files,
        "ingress_throughput": summarize_samples(ingress_samples),
        "settled_throughput": summarize_samples(settled_samples),
    }


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def validate_runtime_profile(runtime: dict, *, strict: bool = True) -> dict:
    profile = runtime.get("runtime_profile")
    expect(isinstance(profile, dict), "runtime diagnostics must include runtime_profile")
    result = {
        "runtime_profile": profile,
        "strict": strict,
        "checks": {},
    }
    if not strict:
        return result
    for path, expected_value in EXPECTED_RUNTIME_PROFILE.items():
        current = profile
        for key in path:
            current = current.get(key) if isinstance(current, dict) else None
        check_name = ".".join(path)
        result["checks"][check_name] = {
            "expected": expected_value,
            "actual": current,
            "ok": current == expected_value,
        }
        expect(
            current == expected_value,
            f"runtime_profile.{check_name} expected {expected_value!r}, got {current!r}",
        )
    object_store = profile.get("object_store") or {}
    expect(
        bool(object_store.get("s3_bucket")),
        "runtime_profile.object_store.s3_bucket must be set for hosted proof",
    )
    expect(
        bool(object_store.get("s3_endpoint_url")),
        "runtime_profile.object_store.s3_endpoint_url must be set for hosted proof",
    )
    expect(
        object_store.get("s3_access_key_present") is True,
        "runtime_profile.object_store.s3_access_key_present must be true",
    )
    expect(
        object_store.get("s3_secret_key_present") is True,
        "runtime_profile.object_store.s3_secret_key_present must be true",
    )
    return result


def run_admin_diagnostics(
    base_url: str,
    *,
    admin_prefix: str,
    api_key: str | None,
    provider_key: str | None,
    timeout_seconds: float,
    strict_runtime_profile: bool = True,
) -> dict:
    results: dict[str, dict] = {}
    runtime = send_json(
        base_url,
        f"{admin_prefix}/runtime",
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    results["runtime"] = runtime
    expect(isinstance(runtime, dict), "runtime diagnostics response must be an object")
    results["runtime_profile_check"] = validate_runtime_profile(
        runtime,
        strict=strict_runtime_profile,
    )

    media = send_json(
        base_url,
        f"{admin_prefix}/media-smoke",
        method="POST",
        payload={},
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    results["media_smoke"] = media
    expect(media.get("gpu_used") is True, "media-smoke must prove gpu_used=true")

    provider_payload = {"provider_key": provider_key} if provider_key else {}
    provider = send_json(
        base_url,
        f"{admin_prefix}/provider-smoke",
        method="POST",
        payload=provider_payload,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    results["provider_smoke"] = provider
    expect(
        provider.get("ok") is True or provider.get("status") in {"ok", "passed", "success"},
        "provider-smoke must succeed with live provider credentials",
    )
    expect(
        provider.get("request_reached_provider") is True,
        "provider-smoke must prove the request reached the live provider",
    )
    expect(
        provider.get("normalized_result_returned") is True,
        "provider-smoke must prove a normalized provider result was returned",
    )
    expect(
        provider.get("provider_response_validated") is True,
        "provider-smoke must validate the provider-specific response shape",
    )

    end_to_end = send_json(
        base_url,
        f"{admin_prefix}/end-to-end-smoke",
        method="POST",
        payload=provider_payload,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    results["end_to_end_smoke"] = end_to_end
    expect(end_to_end.get("gpu_used") is True, "end-to-end-smoke must prove gpu_used=true")
    expect(
        end_to_end.get("ok") is True or end_to_end.get("status") in {"ok", "passed", "success"},
        "end-to-end-smoke must succeed",
    )
    end_to_end_provider = end_to_end.get("provider_smoke") or {}
    expect(
        end_to_end_provider.get("request_reached_provider") is True,
        "end-to-end-smoke must prove the request reached the live provider",
    )
    expect(
        end_to_end_provider.get("normalized_result_returned") is True,
        "end-to-end-smoke must prove a normalized provider result was returned",
    )
    expect(
        end_to_end_provider.get("provider_response_validated") is True,
        "end-to-end-smoke must validate the provider-specific response shape",
    )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify hosted Hearthlight production deployment proof")
    parser.add_argument("--base-url", required=True, help="Hosted API base URL, for example https://host.example")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--admin-prefix", default=DEFAULT_ADMIN_PREFIX)
    parser.add_argument("--provider-key", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--queue-gate", type=float, default=DEFAULT_QUEUE_GATE)
    parser.add_argument("--queue-benchmark-json", action="append", type=Path, default=[])
    parser.add_argument("--settled-benchmark-json", action="append", type=Path, default=[])
    parser.add_argument("--allow-single-client-key", action="store_true")
    parser.add_argument(
        "--skip-runtime-profile-check",
        action="store_true",
        help="Debug only: do not enforce the reference hosted production runtime profile.",
    )
    parser.add_argument("--ingress-endpoint", default=DEFAULT_INGRESS_ENDPOINT)
    parser.add_argument("--ingress-client-key", default=None)
    parser.add_argument("--invalid-ingress-client-key", default=None)
    parser.add_argument("--output", type=Path, default=Path("shared/output/verification/deployment_verification.json"))
    args = parser.parse_args(argv)

    started_at = time.time()
    report = {
        "base_url": args.base_url.rstrip("/"),
        "admin_prefix": args.admin_prefix,
        "started_at": started_at,
        "required_queue_median_submissions_per_second": args.queue_gate,
        "admin_diagnostics": None,
        "ingress_contract": None,
        "queue_only_benchmark": None,
        "settled_benchmark": None,
        "status": "failed",
        "failure_reason": None,
    }
    try:
        report["admin_diagnostics"] = run_admin_diagnostics(
            args.base_url,
            admin_prefix=args.admin_prefix.rstrip("/"),
            api_key=args.api_key,
            provider_key=args.provider_key,
            timeout_seconds=args.timeout_seconds,
            strict_runtime_profile=not args.skip_runtime_profile_check,
        )
        if args.ingress_client_key:
            report["ingress_contract"] = run_ingress_contract_check(
                args.base_url,
                ingress_endpoint=args.ingress_endpoint,
                client_key=args.ingress_client_key,
                invalid_client_key=args.invalid_ingress_client_key,
                timeout_seconds=args.timeout_seconds,
            )
        expect(args.queue_benchmark_json, "at least one --queue-benchmark-json file is required")
        report["queue_only_benchmark"] = validate_queue_benchmarks(
            args.queue_benchmark_json,
            required_median=args.queue_gate,
            require_multiple_client_keys=not args.allow_single_client_key,
        )
        report["settled_benchmark"] = summarize_settled_benchmarks(args.settled_benchmark_json)
        report["status"] = "passed"
    except error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        report["failure_reason"] = f"HTTP {exc.code}: {body}"
    except Exception as exc:
        report["failure_reason"] = str(exc)
    finally:
        report["finished_at"] = time.time()
        report["duration_seconds"] = round(report["finished_at"] - started_at, 3)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True))

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
