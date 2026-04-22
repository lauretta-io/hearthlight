from __future__ import annotations

import logging
import time
from threading import Thread

from omegaconf import DictConfig

from ..shared.constants import FRAME_UPDATE_INTERVAL, FPS_INTERVAL, ModuleNames
from ..shared.database.database import SessionLocal
from ..shared.models import SQLModels
from ..shared.models.DataModels import Status, StatusMessage
from ..shared.rabbit_messenger import StatusPublisher
from ..shared.slave import run_command_listener
from ..shared.utils.backpressure import summarize_queue_backpressure
from ..shared.utils.logger import set_run_logging
from ..shared.utils.micro_batch import (
    KafkaBatchProducer,
    build_asset_reference,
    build_micro_batch_envelope,
    kafka_runtime_available,
    utc_now_iso,
)
from ..shared.utils.runtime_guard import get_dead_thread_names
from ..shared.utils.timer import LoopTimer

logger = logging.getLogger(__name__)


class Exporter(Thread):
    def __init__(self, cfg: DictConfig, status_publisher: StatusPublisher):
        super().__init__(name=self.__class__.__name__, daemon=True)
        set_run_logging(cfg, module_name=ModuleNames.EXPORTER)
        self.process = False
        self.status_publisher = status_publisher
        self.run_identifier = getattr(cfg, "run_id", None)
        self.export_sink_key = getattr(cfg, "export_sink", None)
        self.sink_cfg = dict(getattr(cfg, "exporters", {}).get(self.export_sink_key, {}))
        self.enabled = bool(self.sink_cfg.get("enabled", False))
        self.flush_interval_seconds = float(
            self.sink_cfg.get("batch", {}).get("flush_interval_seconds", 5.0)
        )
        self.max_records = int(self.sink_cfg.get("batch", {}).get("max_records", 100))
        self.topics = dict(self.sink_cfg.get("topics") or {})
        self.last_flush_at = None
        self.last_ids = {
            "incident": 0,
            "person": 0,
            "bag": 0,
            "anomaly": 0,
            "frame": 0,
        }
        self.health_detail = None
        self.producer = None
        if self.enabled:
            available, detail = kafka_runtime_available()
            if not available:
                self.health_detail = detail
            else:
                try:
                    self.producer = KafkaBatchProducer(
                        list(self.sink_cfg.get("bootstrap_servers") or [])
                    )
                except Exception as exc:
                    self.health_detail = str(exc)

    def get_run_row(self, db):
        if not self.run_identifier:
            return None
        return db.query(SQLModels.Run).filter_by(run_identifier=self.run_identifier).first()

    def build_asset_references(self, db, run_row, frame_rows):
        asset_references = []
        recordings = (
            db.query(SQLModels.CameraRecording)
            .filter_by(run_id=run_row.id, is_deleted=False)
            .order_by(SQLModels.CameraRecording.id.asc())
            .all()
        )
        for recording in recordings:
            if recording.cam_recording_path:
                asset_references.append(
                    build_asset_reference(
                        uri=recording.cam_recording_path,
                        media_type="video/mp4",
                        producer=ModuleNames.INGESTOR,
                    )
                )
        for frame_row in frame_rows:
            if frame_row.path:
                asset_references.append(
                    build_asset_reference(
                        uri=frame_row.path,
                        media_type="image/jpeg",
                        producer=ModuleNames.INGESTOR,
                        timestamp=(
                            frame_row.datetime.isoformat()
                            if frame_row.datetime is not None
                            else None
                        ),
                    )
                )
        return asset_references

    def fetch_batches(self, db):
        run_row = self.get_run_row(db)
        if run_row is None:
            return None

        incidents = (
            db.query(SQLModels.Incident)
            .filter(
                SQLModels.Incident.run_id == run_row.id,
                SQLModels.Incident.is_deleted.is_(False),
                SQLModels.Incident.id > self.last_ids["incident"],
            )
            .order_by(SQLModels.Incident.id.asc())
            .limit(self.max_records)
            .all()
        )
        persons = (
            db.query(SQLModels.Person)
            .filter(
                SQLModels.Person.run_id == run_row.id,
                SQLModels.Person.is_deleted.is_(False),
                SQLModels.Person.id > self.last_ids["person"],
            )
            .order_by(SQLModels.Person.id.asc())
            .limit(self.max_records)
            .all()
        )
        bags = (
            db.query(SQLModels.Bag)
            .filter(
                SQLModels.Bag.run_id == run_row.id,
                SQLModels.Bag.is_deleted.is_(False),
                SQLModels.Bag.id > self.last_ids["bag"],
            )
            .order_by(SQLModels.Bag.id.asc())
            .limit(self.max_records)
            .all()
        )
        anomalies = (
            db.query(SQLModels.AnomalyEvent)
            .filter(
                SQLModels.AnomalyEvent.run_id == run_row.id,
                SQLModels.AnomalyEvent.is_deleted.is_(False),
                SQLModels.AnomalyEvent.id > self.last_ids["anomaly"],
            )
            .order_by(SQLModels.AnomalyEvent.id.asc())
            .limit(self.max_records)
            .all()
        )
        frames = (
            db.query(SQLModels.Frame)
            .filter(
                SQLModels.Frame.run_id == run_row.id,
                SQLModels.Frame.is_deleted.is_(False),
                SQLModels.Frame.id > self.last_ids["frame"],
            )
            .order_by(SQLModels.Frame.id.asc())
            .limit(self.max_records)
            .all()
        )

        incident_records = [
            {
                "record_type": "incident",
                "incident_id": incident.id,
                "incident_type": incident.incident_type,
                "status": incident.status,
                "camera_id": incident.camera_id,
                "zone_id": incident.zone_id,
                "timestamp": incident.timestamp,
            }
            for incident in incidents
        ]
        entity_records = [
            {
                "record_type": "entity",
                "entity_kind": "person",
                "entity_id": person.id,
                "created_at": person.created_at.isoformat() if person.created_at is not None else None,
            }
            for person in persons
        ] + [
            {
                "record_type": "entity",
                "entity_kind": "bag",
                "entity_id": bag.id,
                "created_at": bag.created_at.isoformat() if bag.created_at is not None else None,
            }
            for bag in bags
        ]
        anomaly_records = [
            {
                "record_type": "anomaly",
                "event_id": anomaly.event_key,
                "source_id": anomaly.source_template_id,
                "frame_id": anomaly.frame_id,
                "model_key": anomaly.model_key,
                "category": anomaly.category,
                "score": anomaly.score,
                "reasoning": anomaly.reasoning,
            }
            for anomaly in anomalies
        ]
        asset_references = self.build_asset_references(db, run_row, frames)

        return {
            "run_row": run_row,
            "incident_records": incident_records,
            "entity_records": entity_records,
            "anomaly_records": anomaly_records,
            "algorithm_records": incident_records + entity_records + anomaly_records,
            "asset_references": asset_references,
            "last_ids": {
                "incident": incidents[-1].id if incidents else self.last_ids["incident"],
                "person": persons[-1].id if persons else self.last_ids["person"],
                "bag": bags[-1].id if bags else self.last_ids["bag"],
                "anomaly": anomalies[-1].id if anomalies else self.last_ids["anomaly"],
                "frame": frames[-1].id if frames else self.last_ids["frame"],
            },
        }

    def publish_batches(self, batches):
        if not self.enabled:
            return 0
        if self.producer is None:
            return (
                len(batches["incident_records"])
                + len(batches["entity_records"])
                + len(batches["anomaly_records"])
            )

        run_identifier = batches["run_row"].run_identifier
        publish_specs = [
            ("algorithm", batches["algorithm_records"]),
            ("incidents", batches["incident_records"]),
            ("entities", batches["entity_records"]),
            ("anomalies", batches["anomaly_records"]),
        ]
        for batch_type, records in publish_specs:
            topic = self.topics.get(batch_type)
            if not topic or not records:
                continue
            envelope = build_micro_batch_envelope(
                run_identifier=run_identifier,
                batch_type=batch_type,
                records=records,
                asset_references=batches["asset_references"],
                exporter_key=self.export_sink_key or "unconfigured",
            )
            self.producer.publish(topic, envelope)
        self.last_ids.update(batches["last_ids"])
        self.last_flush_at = utc_now_iso()
        return 0

    def emit_status(self, queued_records: int):
        queue_depths = {"pending_records": queued_records}
        self.status_publisher.publish(
            StatusMessage(
                status=Status.INFO,
                module=ModuleNames.EXPORTER,
                extra={
                    "queue_depths": queue_depths,
                    "backpressure": summarize_queue_backpressure(queue_depths),
                    "exporter_status": {
                        "sink_key": self.export_sink_key,
                        "enabled": self.enabled,
                        "healthy": self.health_detail is None,
                        "detail": self.health_detail,
                        "last_flush_at": self.last_flush_at,
                        "queued_records": queued_records,
                    },
                    "healthy": self.health_detail is None,
                    "detail": self.health_detail,
                    "last_flush_at": self.last_flush_at,
                    "queued_records": queued_records,
                },
            )
        )

    def run(self):
        self.process = True
        timer = LoopTimer(log_interval=FPS_INTERVAL, task=ModuleNames.EXPORTER, abbrev="exp")
        timer.start()
        while self.process:
            dead_workers = get_dead_thread_names({})
            if dead_workers:
                logger.warning("Unexpected worker state in exporter: %s", dead_workers)
            queued_records = 0
            try:
                with SessionLocal() as db:
                    batches = self.fetch_batches(db)
                if batches is not None:
                    queued_records = (
                        len(batches["incident_records"])
                        + len(batches["entity_records"])
                        + len(batches["anomaly_records"])
                    )
                    if queued_records:
                        try:
                            queued_records = self.publish_batches(batches)
                            self.health_detail = None
                        except Exception as exc:
                            logger.exception("Failed to export micro-batch")
                            self.health_detail = str(exc)
                            queued_records = (
                                len(batches["incident_records"])
                                + len(batches["entity_records"])
                                + len(batches["anomaly_records"])
                            )
            except Exception as exc:
                logger.exception("Exporter cycle failed")
                self.health_detail = str(exc)

            self.emit_status(queued_records)
            timer.loop()
            time.sleep(max(self.flush_interval_seconds, FRAME_UPDATE_INTERVAL))

    def stop(self):
        self.process = False


if __name__ == "__main__":
    run_command_listener(ModuleNames.EXPORTER, Exporter)
