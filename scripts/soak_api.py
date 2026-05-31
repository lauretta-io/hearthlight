#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from importlib.util import find_spec
import json
import os
from pathlib import Path
import threading
import time
from urllib import parse, request


PSUTIL_AVAILABLE = find_spec("psutil") is not None
if PSUTIL_AVAILABLE:
    import psutil  # type: ignore
else:
    psutil = None


DEFAULT_ENDPOINTS = (
    "/monitoring/overview?limit=8",
    "/model-logs?page=1&page_size=20",
    "/operations/incidents?filter_mode=all&include_crop=false",
    "/settings/input-sources",
)


@dataclass
class Sample:
    timestamp: float
    rss_mb: float | None
    thread_count: int | None
    open_fds: int | None


def fetch_json(base_url: str, endpoint: str):
    started_at = time.time()
    with request.urlopen(parse.urljoin(base_url, endpoint), timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return {
        "endpoint": endpoint,
        "latency_ms": round((time.time() - started_at) * 1000, 2),
        "payload": payload,
    }


def poll_sse(base_url: str, stop_event: threading.Event, counters: dict[str, int]):
    req = request.Request(
        parse.urljoin(base_url, "/operations/events"),
        headers={"Accept": "text/event-stream"},
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            for raw_line in response:
                if stop_event.is_set():
                    break
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if line.startswith("event:"):
                    counters[line.split(":", 1)[1].strip()] += 1
    except Exception:
        counters["errors"] += 1


def collect_process_sample(started_at: float) -> Sample:
    process = psutil.Process(os.getpid()) if psutil is not None else None
    rss_mb = None
    thread_count = None
    open_fds = None
    if process is not None:
        rss_mb = round(process.memory_info().rss / (1024 * 1024), 2)
        thread_count = int(process.num_threads())
        if hasattr(process, "num_fds"):
            open_fds = int(process.num_fds())
        elif hasattr(process, "num_handles"):
            open_fds = int(process.num_handles())
    return Sample(
        timestamp=time.time() - started_at,
        rss_mb=rss_mb,
        thread_count=thread_count,
        open_fds=open_fds,
    )


def slope(samples: list[Sample], field_name: str):
    valid = [
        (sample.timestamp, getattr(sample, field_name))
        for sample in samples
        if getattr(sample, field_name) is not None
    ]
    if len(valid) < 2:
        return None
    first_t, first_value = valid[0]
    last_t, last_value = valid[-1]
    elapsed_minutes = max((last_t - first_t) / 60.0, 1e-6)
    return round((last_value - first_value) / elapsed_minutes, 4)


def main():
    parser = argparse.ArgumentParser(description="Hearthlight API/SSE soak harness")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--sse-clients", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("shared/output/soak/api_soak_summary.json"))
    args = parser.parse_args()

    stop_event = threading.Event()
    started_at = time.time()
    sse_counters = defaultdict(int)
    process_samples: list[Sample] = []
    latency_samples: list[dict] = []

    sse_threads = [
        threading.Thread(
            target=poll_sse,
            args=(args.base_url, stop_event, sse_counters),
            daemon=True,
        )
        for _index in range(max(0, args.sse_clients))
    ]
    for thread in sse_threads:
        thread.start()

    try:
        while time.time() - started_at < args.duration_seconds:
            process_samples.append(collect_process_sample(started_at))
            with ThreadPoolExecutor(max_workers=len(DEFAULT_ENDPOINTS)) as pool:
                future_results = [
                    pool.submit(fetch_json, args.base_url, endpoint)
                    for endpoint in DEFAULT_ENDPOINTS
                ]
                for future in future_results:
                    try:
                        latency_samples.append(future.result())
                    except Exception as exc:
                        latency_samples.append({"endpoint": "error", "error": str(exc)})
            time.sleep(args.poll_interval_seconds)
    finally:
        stop_event.set()
        for thread in sse_threads:
            thread.join(timeout=2)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "started_at": started_at,
        "duration_seconds": args.duration_seconds,
        "base_url": args.base_url,
        "sse_clients": args.sse_clients,
        "sse_events": dict(sse_counters),
        "latency": {
            "samples": latency_samples,
            "max_ms": max((sample.get("latency_ms", 0) for sample in latency_samples), default=0),
        },
        "process": {
            "baseline": process_samples[0].__dict__ if process_samples else None,
            "max_rss_mb": max((sample.rss_mb or 0 for sample in process_samples), default=0),
            "max_thread_count": max((sample.thread_count or 0 for sample in process_samples), default=0),
            "max_open_fds": max((sample.open_fds or 0 for sample in process_samples), default=0),
            "rss_mb_per_minute": slope(process_samples, "rss_mb"),
            "threads_per_minute": slope(process_samples, "thread_count"),
        },
        "failure_reason": None,
    }
    args.output.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
