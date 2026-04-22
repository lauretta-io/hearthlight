#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from urllib import request

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from shared.database.database import SessionLocal
    from shared.models import SQLModels
except ModuleNotFoundError:
    SessionLocal = None
    SQLModels = None

SEED_DIR = REPO_ROOT / "deploy" / "seeds" / "control_plane"
MODEL_BINDINGS_SEED = SEED_DIR / "model_bindings.seed.yaml"
INPUT_SOURCES_SEED = SEED_DIR / "input_sources.seed.json"
MODEL_BINDINGS_TARGET = REPO_ROOT / "shared" / "configs" / "model_bindings.yaml"


def load_sources() -> list[dict]:
    if not INPUT_SOURCES_SEED.exists():
        return []
    return json.loads(INPUT_SOURCES_SEED.read_text())


def load_model_binding_defaults() -> dict[str, str]:
    defaults: dict[str, str] = {}
    in_defaults = False
    for raw_line in MODEL_BINDINGS_SEED.read_text().splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "defaults:":
            in_defaults = True
            continue
        if not in_defaults:
            continue
        if not raw_line.startswith("  "):
            break
        key, _, value = stripped.partition(":")
        defaults[key.strip()] = value.strip()
    return defaults


def seed_input_sources() -> int:
    if SessionLocal is None or SQLModels is None:
        raise RuntimeError("database seed path is unavailable because SQLAlchemy is not installed")
    seeded_sources = load_sources()
    with SessionLocal() as db:
        for existing_row in db.query(SQLModels.InputSourceTemplate).filter_by(is_deleted=False).all():
            existing_row.is_deleted = True
        for order, source in enumerate(seeded_sources):
            db.add(
                SQLModels.InputSourceTemplate(
                    kind=source["kind"],
                    label=source["label"],
                    source_value=(
                        None if source["kind"] == "video_upload" else str(source["source_value"])
                    ),
                    upload_id=source.get("upload_id"),
                    tasks=list(source["tasks"]),
                    enabled=bool(source.get("enabled", False)),
                    sort_order=int(source.get("order", order)),
                    detector_model_key=source.get("detector_model_key"),
                    tracker_model_key=source.get("tracker_model_key"),
                    reid_model_key=source.get("reid_model_key"),
                    anomaly_stage_1_model_key=source.get("anomaly_stage_1_model_key"),
                    anomaly_stage_2_model_key=source.get("anomaly_stage_2_model_key"),
                )
            )
        db.commit()
    return len(seeded_sources)


def seed_input_sources_via_api(base_url: str) -> int:
    seeded_sources = load_sources()
    payload = json.dumps(seeded_sources).encode()
    req = request.Request(
        base_url.rstrip("/") + "/sources",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with request.urlopen(req, timeout=20) as response:
        json.load(response)
    return len(seeded_sources)


def seed_model_bindings_via_api(base_url: str) -> None:
    bindings = [
        {
            "stage": stage,
            "model_key": model_key,
            "binding_scope": "default",
        }
        for stage, model_key in load_model_binding_defaults().items()
    ]
    req = request.Request(
        base_url.rstrip("/") + "/model-bindings",
        data=json.dumps(bindings).encode(),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with request.urlopen(req, timeout=20) as response:
        json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed deployment control-plane defaults")
    parser.add_argument(
        "--base-url",
        default=None,
        help="optional control-plane API base URL to use when local DB dependencies are unavailable",
    )
    args = parser.parse_args()

    MODEL_BINDINGS_TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(MODEL_BINDINGS_SEED, MODEL_BINDINGS_TARGET)
    print(f"Seeded model bindings from {MODEL_BINDINGS_SEED}")
    base_url = args.base_url
    if SessionLocal is not None and SQLModels is not None:
        source_count = seed_input_sources()
        print(f"Seeded {source_count} control-plane input source row(s) from {INPUT_SOURCES_SEED}")
        return 0

    if base_url:
        seed_model_bindings_via_api(base_url)
        source_count = seed_input_sources_via_api(base_url)
        print(f"Seeded {source_count} control-plane input source row(s) through {base_url}")
        return 0

    print(
        "Skipped DB/API source seeding because SQLAlchemy is not installed locally and no --base-url was provided."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
