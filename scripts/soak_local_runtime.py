#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from urllib import parse, request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_repo_env():
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())
    if os.environ.get("POSTGRES_HOST") == "db":
        os.environ["POSTGRES_HOST"] = "127.0.0.1"
        os.environ["POSTGRES_PORT"] = os.environ.get("POSTGRES_EXT_PORT", os.environ.get("POSTGRES_PORT", "5433"))


load_repo_env()

from shared.database.database import SessionLocal
from shared.models import SQLModels
from shared.utils.file_retention import directory_size_bytes


DEFAULT_OUTPUT_DIRS = (
    Path("shared/output"),
    Path("src/shared/output"),
)


def fetch_json(base_url: str, endpoint: str):
    with request.urlopen(parse.urljoin(base_url, endpoint), timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def collect_db_counts():
    with SessionLocal() as db:
        return {
            "model_result_logs": db.query(SQLModels.ModelResultLog).filter_by(is_deleted=False).count(),
            "incidents": db.query(SQLModels.Incident).filter_by(is_deleted=False).count(),
            "anomaly_events": db.query(SQLModels.AnomalyEvent).filter_by(is_deleted=False).count(),
            "frames": db.query(SQLModels.Frame).filter_by(is_deleted=False).count(),
            "person_instances": db.query(SQLModels.PersonInstance).filter_by(is_deleted=False).count(),
            "bag_instances": db.query(SQLModels.BagInstance).filter_by(is_deleted=False).count(),
        }


def collect_output_sizes():
    totals = {}
    for path in DEFAULT_OUTPUT_DIRS:
        totals[str(path)] = directory_size_bytes(path) or 0
    return totals


def main():
    parser = argparse.ArgumentParser(description="Hearthlight local-runtime soak sampler")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    parser.add_argument("--output", type=Path, default=Path("shared/output/soak/local_runtime_soak_summary.json"))
    args = parser.parse_args()

    samples = []
    started_at = time.time()
    while time.time() - started_at < args.duration_seconds:
        resources = fetch_json(args.base_url, "/system/resources")
        overview = fetch_json(args.base_url, "/monitoring/overview?limit=4")
        samples.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "resources": resources,
                "db_counts": collect_db_counts(),
                "output_sizes": collect_output_sizes(),
                "module_status": overview.get("resources", {}).get("module_status", {}),
            }
        )
        time.sleep(args.poll_interval_seconds)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "duration_seconds": args.duration_seconds,
        "sample_count": len(samples),
        "baseline": samples[0] if samples else None,
        "latest": samples[-1] if samples else None,
        "samples": samples,
    }
    args.output.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
