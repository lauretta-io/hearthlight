from __future__ import annotations

from datetime import datetime, timezone
from importlib.util import find_spec
import json
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
    exporter_key: str,
) -> dict[str, Any]:
    return {
        "generated_at": utc_now_iso(),
        "run_identifier": run_identifier,
        "batch_type": batch_type,
        "record_count": len(records),
        "exporter_key": exporter_key,
        "records": records,
        "asset_references": asset_references,
    }


def kafka_runtime_available() -> tuple[bool, str | None]:
    if find_spec("kafka") is not None:
        return True, None
    if find_spec("confluent_kafka") is not None:
        return True, None
    return False, "kafka client dependency is not installed"


class KafkaBatchProducer:
    def __init__(self, bootstrap_servers: list[str]):
        self.bootstrap_servers = bootstrap_servers
        self.mode = None
        self._producer = None
        if find_spec("kafka") is not None:
            from kafka import KafkaProducer  # type: ignore

            self._producer = KafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda value: json.dumps(value).encode("utf-8"),
            )
            self.mode = "kafka-python"
        elif find_spec("confluent_kafka") is not None:
            from confluent_kafka import Producer  # type: ignore

            self._producer = Producer({"bootstrap.servers": ",".join(bootstrap_servers)})
            self.mode = "confluent-kafka"
        else:
            raise RuntimeError("no kafka client library is installed")

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        assert self._producer is not None
        if self.mode == "kafka-python":
            self._producer.send(topic, payload)
            self._producer.flush()
            return
        self._producer.produce(topic, json.dumps(payload).encode("utf-8"))
        self._producer.flush()

