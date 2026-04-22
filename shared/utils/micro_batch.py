from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_asset_reference(
    *,
    uri: str,
    media_type: str,
    checksum_sha256: str | None = None,
    size_bytes: int | None = None,
    producer: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    return {
        "uri": uri,
        "media_type": media_type,
        "checksum_sha256": checksum_sha256,
        "size_bytes": size_bytes,
        "producer": producer,
        "timestamp": timestamp,
    }


def build_micro_batch_envelope(
    *,
    run_identifier: str | None,
    batch_type: str,
    records: list[dict[str, Any]],
    asset_references: list[dict[str, Any]],
    sink_key: str,
) -> dict[str, Any]:
    return {
        "generated_at": utc_now_iso(),
        "run_identifier": run_identifier,
        "batch_type": batch_type,
        "record_count": len(records),
        "sink_key": sink_key,
        "records": records,
        "asset_references": asset_references,
    }
