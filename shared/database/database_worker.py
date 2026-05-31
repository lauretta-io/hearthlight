from collections import defaultdict
from datetime import datetime
import os
from pathlib import Path
import json
from typing import TypeVar
import logging

from sqlalchemy.exc import SQLAlchemyError

from .database import SessionLocal
from ..models import SQLModels
from ..models.SQLModels import Base
from ..models import DataModels
from ..utils.alert_rules import (
    ALERT_SIGNAL_FAMILY_ANOMALY_ACTIVITY,
    ALERT_SIGNAL_FAMILY_ANOMALY_OBJECT,
    ALERT_SIGNAL_FAMILY_DETECTOR,
    TRIGGER_KEY_ALERT_RULE,
    build_alert_incident_title,
    ensure_alert_rule_tables,
    resolve_alert_level_label,
)
from ..utils.backoff import with_exponential_backoff
from ..constants import DetectorClasses, IncidentStatus, IncidentType
from ..utils.model_registry import (
    MODEL_STAGE_ANOMALY_STAGE_1,
    MODEL_STAGE_ANOMALY_STAGE_2,
    MODEL_STAGE_DETECTOR,
    build_model_display_name,
    build_default_bindings,
    get_registration,
    load_registry_bundle,
    resolve_bindings_for_source,
)
from ..utils.monitoring_feed import parse_serialized_json
from ..utils.apple_messages_notifications import (
    ensure_apple_message_subscription_tables,
    queue_apple_message_trigger_notifications,
)
from ..utils.action_connectors import (
    build_action_trigger_payload,
    ensure_action_connector_tables,
    queue_action_trigger_notifications,
    validate_action_connector_config,
)
from ..utils.claude_api_connector import (
    build_claude_trigger_payload,
    ensure_claude_api_connector_tables,
    queue_claude_api_trigger_notifications,
)
from ..utils.connector_endpoints import (
    ACTION_CONNECTOR_KEYS,
    CONNECTOR_KEY_APPLE_MESSAGES,
    CONNECTOR_KEY_CLAUDE_API,
    CONNECTOR_KEY_GOVEE,
    CONNECTOR_KEY_TELEGRAM,
    get_connector_endpoint_config,
    list_connector_endpoint_rows,
)
from ..utils.govee_connector import (
    ensure_govee_connector_tables,
    queue_govee_trigger_actions,
)
from ..utils.telegram_notifications import (
    build_trigger_notification_text,
    ensure_telegram_subscription_tables,
    queue_telegram_trigger_notifications,
)

logger = logging.getLogger(__name__)
SQLModel = TypeVar("SQLModel", bound=Base)
MODEL_RESULT_LOG_RETAIN_MAX = int(
    os.environ.get("HEARTHLIGHT_MODEL_RESULT_LOG_RETAIN_MAX", "50000")
)
MODEL_RESULT_LOG_PRUNE_INTERVAL = int(
    os.environ.get("HEARTHLIGHT_MODEL_RESULT_LOG_PRUNE_INTERVAL", "100")
)


class DatabaseWorker:
    run_id = None

    @classmethod
    @with_exponential_backoff(max_tries=10, max_delay=10)
    def set_run_id(cls, run_identifier: str):
        with SessionLocal() as db:
            run = (
                db.query(SQLModels.Run).filter_by(run_identifier=run_identifier).first()
            )
            if not run:
                raise Exception("Run identifier not found in database")
        cls.run_id = run.id

    @classmethod
    def get_cameras(cls):
        with SessionLocal() as db:
            return (
                db.query(SQLModels.CameraRecording).filter_by(run_id=cls.run_id).all()
            )

    def __init__(self):
        self.confirmed_persons = set()
        self.confirmed_bags = set()
        self.journey_node_ids = defaultdict(lambda: defaultdict(dict))
        self.source_template_ids_by_camera_id = {}
        self.source_rows_by_id = {}
        self.runtime_binding_defaults = None
        self.runtime_registry_bundle = None
        self.active_run_db_id = None
        self.model_log_writes_since_prune = 0

        self.SessionLocal = SessionLocal

    def reset_runtime_caches(self):
        self.confirmed_persons.clear()
        self.confirmed_bags.clear()
        self.journey_node_ids.clear()
        self.source_template_ids_by_camera_id.clear()
        self.source_rows_by_id.clear()
        self.runtime_binding_defaults = None
        self.runtime_registry_bundle = None

    def _maybe_reset_for_run(self):
        if DatabaseWorker.run_id != self.active_run_db_id:
            self.reset_runtime_caches()
            self.active_run_db_id = DatabaseWorker.run_id

    def prune_model_result_logs(self):
        if MODEL_RESULT_LOG_RETAIN_MAX <= 0:
            return
        retained_rows = (
            self.db.query(SQLModels.ModelResultLog.id)
            .filter_by(is_deleted=False)
            .order_by(SQLModels.ModelResultLog.created_at.desc(), SQLModels.ModelResultLog.id.desc())
            .offset(MODEL_RESULT_LOG_RETAIN_MAX)
            .all()
        )
        stale_ids = [row[0] for row in retained_rows]
        if not stale_ids:
            return
        current_time = datetime.now().isoformat()
        (
            self.db.query(SQLModels.ModelResultLog)
            .filter(SQLModels.ModelResultLog.id.in_(stale_ids))
            .update(
                {
                    SQLModels.ModelResultLog.is_deleted: True,
                    SQLModels.ModelResultLog.deleted_at: current_time,
                    SQLModels.ModelResultLog.updated_at: current_time,
                },
                synchronize_session=False,
            )
        )
        self.db.commit()

    # CRUD operations

    def create(self, item: SQLModel) -> SQLModel | None:
        try:
            self.db.add(item)
            self.db.commit()
            self.db.refresh(item)
            return item
        except SQLAlchemyError:
            self.db.rollback()
            logger.exception("Failed to create item in database")

    def get(self, model: type[SQLModel], id_: int) -> SQLModel | None:
        db_model = self.db.query(model).get(id_)
        return db_model

    def update(self, item: SQLModel) -> SQLModel | None:
        try:
            item.updated_at = datetime.now().isoformat()
            self.db.commit()
            self.db.refresh(item)
            return item
        except SQLAlchemyError:
            self.db.rollback()
            logger.exception("Failed to update item in database")

    def batch_update(self, items: list[SQLModel]) -> None:
        try:
            updated_at = datetime.now().isoformat()
            for item in items:
                item.updated_at = updated_at
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            logger.exception("Failed to update items in database")

    def delete(self, item: SQLModel) -> None:
        try:
            item.is_deleted = True
            current_time = datetime.now().isoformat()
            item.deleted_at = current_time
            item.updated_at = current_time
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            logger.exception("Failed to delete item in database")

    def get_persons(self):
        with self.SessionLocal() as self.db:
            db_models = self.db.query(SQLModels.Person).all()
        return db_models

    def get_source_template_id_for_camera(self, camera_id: int | None) -> int | None:
        if camera_id is None:
            return None
        if camera_id in self.source_template_ids_by_camera_id:
            return self.source_template_ids_by_camera_id[camera_id]
        recording = (
            self.db.query(SQLModels.CameraRecording)
            .filter_by(run_id=DatabaseWorker.run_id, cam_id=camera_id)
            .order_by(SQLModels.CameraRecording.id.desc())
            .first()
        )
        source_template_id = (
            recording.source_template_id if recording is not None else None
        )
        self.source_template_ids_by_camera_id[camera_id] = source_template_id
        return source_template_id

    def get_source_row_by_id(self, source_id: int | None):
        if source_id is None:
            return None
        db = getattr(self, "db", None)
        if db is not None:
            return db.get(SQLModels.InputSourceTemplate, source_id)
        if source_id in self.source_rows_by_id:
            return self.source_rows_by_id[source_id]
        with self.SessionLocal() as session:
            source_row = session.get(SQLModels.InputSourceTemplate, source_id)
        self.source_rows_by_id[source_id] = source_row
        return source_row

    def get_runtime_binding_defaults(self) -> dict[str, str | None]:
        if self.runtime_binding_defaults is not None:
            return self.runtime_binding_defaults
        bundle = self.get_runtime_registry_bundle()
        self.runtime_binding_defaults = build_default_bindings(bundle)
        return self.runtime_binding_defaults

    def get_runtime_registry_bundle(self) -> dict:
        if self.runtime_registry_bundle is None:
            self.runtime_registry_bundle = load_registry_bundle()
        return self.runtime_registry_bundle

    def get_model_display_name(self, stage: str, model_key: str | None) -> str | None:
        if not model_key:
            return None
        bundle = self.get_runtime_registry_bundle()
        registration = get_registration(bundle, stage, model_key)
        if registration is None:
            return model_key
        return build_model_display_name(stage, model_key, registration)

    def resolve_model_keys_for_source(self, source_id: int | None) -> dict[str, str | None]:
        source_row = self.get_source_row_by_id(source_id)
        if source_row is None:
            return {}
        return resolve_bindings_for_source(
            source_row,
            self.get_runtime_binding_defaults(),
        )

    def create_model_result_log(
        self,
        *,
        source_id: int | None,
        source_label: str | None,
        camera_id: int | None,
        stage: str,
        model_key: str | None,
        frame_id: int | None,
        result_summary: str,
        result_payload: dict,
    ):
        if not model_key or not result_summary:
            return None
        log_row = self.create(
            SQLModels.ModelResultLog(
                run_id=DatabaseWorker.run_id,
                source_template_id=source_id,
                source_label=source_label,
                camera_id=camera_id,
                stage=stage,
                model_key=model_key,
                model_display_name=self.get_model_display_name(stage, model_key),
                frame_id=frame_id,
                result_summary=result_summary,
                result_payload_json=json.dumps(result_payload),
            )
        )
        if log_row is not None:
            self.model_log_writes_since_prune += 1
            if self.model_log_writes_since_prune >= max(1, MODEL_RESULT_LOG_PRUNE_INTERVAL):
                self.prune_model_result_logs()
                self.model_log_writes_since_prune = 0
        return log_row

    def create_detector_model_log(self, frame: DataModels.Frame, frame_id: int):
        source_id = self.get_source_template_id_for_camera(frame.cam_id)
        source_row = self.get_source_row_by_id(source_id)
        model_keys = self.resolve_model_keys_for_source(source_id)
        detector_model_key = model_keys.get(MODEL_STAGE_DETECTOR)
        class_buckets: dict[str, list[float]] = defaultdict(list)
        detections_payload = []
        for detection in frame.detections:
            clss = str(detection.clss or "").strip() or "unknown"
            confidence = float(detection.confidence or 0.0)
            class_buckets[clss].append(confidence)
            detections_payload.append(
                {
                    "class": clss,
                    "confidence": round(confidence, 4),
                    "bbox": list(detection.bbox.tolist() if hasattr(detection.bbox, "tolist") else detection.bbox),
                }
            )
        if class_buckets:
            parts = [
                f"{clss} x{len(confidences)} (max {max(confidences):.2f})"
                for clss, confidences in sorted(class_buckets.items())
            ]
            summary = f"{len(frame.detections)} detections · {'; '.join(parts)}"
        else:
            summary = "0 detections"
        self.create_model_result_log(
            source_id=source_id,
            source_label=getattr(source_row, "label", None),
            camera_id=frame.cam_id,
            stage=MODEL_STAGE_DETECTOR,
            model_key=detector_model_key,
            frame_id=frame_id,
            result_summary=summary,
            result_payload={
                "detection_count": len(frame.detections),
                "detections": detections_payload,
            },
        )

    def build_anomaly_log_summary(
        self,
        event: DataModels.AnomalyEvent,
        *,
        include_reasoning: bool = False,
    ) -> str:
        parts = [f"Score {float(event.score or 0.0):.2f}", event.title or event.category]
        if event.visible_items:
            parts.append(f"items: {', '.join(event.visible_items)}")
        if event.visible_activities:
            parts.append(f"behaviors: {', '.join(event.visible_activities)}")
        if include_reasoning and event.reasoning:
            parts.append(event.reasoning.strip())
        return " · ".join(part for part in parts if part)

    def create_anomaly_model_logs(self, event: DataModels.AnomalyEvent):
        source_id = event.source_id or self.get_source_template_id_for_camera(event.camera_id)
        source_row = self.get_source_row_by_id(source_id)
        model_keys = self.resolve_model_keys_for_source(source_id)
        stage_1_model_key = event.stage_1_model_key or model_keys.get(MODEL_STAGE_ANOMALY_STAGE_1)
        stage_2_model_key = event.stage_2_model_key or event.model_key or model_keys.get(MODEL_STAGE_ANOMALY_STAGE_2)
        payload = {
            "category": event.category,
            "score": round(float(event.score or 0.0), 4),
            "title": event.title,
            "visible_items": list(event.visible_items),
            "visible_activities": list(event.visible_activities),
            "reasoning": event.reasoning,
        }
        self.create_model_result_log(
            source_id=source_id,
            source_label=getattr(source_row, "label", None),
            camera_id=event.camera_id,
            stage=MODEL_STAGE_ANOMALY_STAGE_1,
            model_key=stage_1_model_key,
            frame_id=event.frame_id,
            result_summary=self.build_anomaly_log_summary(event),
            result_payload=payload,
        )
        self.create_model_result_log(
            source_id=source_id,
            source_label=getattr(source_row, "label", None),
            camera_id=event.camera_id,
            stage=MODEL_STAGE_ANOMALY_STAGE_2,
            model_key=stage_2_model_key,
            frame_id=event.frame_id,
            result_summary=self.build_anomaly_log_summary(event, include_reasoning=True),
            result_payload=payload,
        )

    def create_anomaly_evaluation_logs(
        self,
        *,
        source_id: int | None,
        camera_id: int | None,
        frame_id: int | None,
        stage_1_model_key: str | None,
        stage_2_model_key: str | None,
        score: float,
        category: str | None,
        reasoning: str | None,
        promoted: bool,
    ):
        source_row = self.get_source_row_by_id(source_id)
        base_payload = {
            "score": round(float(score or 0.0), 4),
            "category": category,
            "reasoning": reasoning,
            "promoted": promoted,
            "visible_items": [],
            "visible_activities": [],
        }
        stage_1_summary = (
            f"Candidate score {float(score or 0.0):.2f} · {category or 'no category'}"
            if promoted
            else f"No anomaly candidate · Score {float(score or 0.0):.2f}"
        )
        stage_2_summary = (
            f"Promoted anomaly candidate · Score {float(score or 0.0):.2f}"
            if promoted
            else f"No anomaly returned · Score {float(score or 0.0):.2f}"
        )
        self.create_model_result_log(
            source_id=source_id,
            source_label=getattr(source_row, "label", None),
            camera_id=camera_id,
            stage=MODEL_STAGE_ANOMALY_STAGE_1,
            model_key=stage_1_model_key,
            frame_id=frame_id,
            result_summary=stage_1_summary,
            result_payload=base_payload,
        )
        self.create_model_result_log(
            source_id=source_id,
            source_label=getattr(source_row, "label", None),
            camera_id=camera_id,
            stage=MODEL_STAGE_ANOMALY_STAGE_2,
            model_key=stage_2_model_key,
            frame_id=frame_id,
            result_summary=stage_2_summary,
            result_payload=base_payload,
        )

    def get_enabled_alert_rules(
        self,
        *,
        source_id: int | None,
        signal_family: str,
    ) -> list[SQLModels.TriggerRule]:
        if source_id is None:
            return []
        ensure_alert_rule_tables()
        rows = (
            self.db.query(SQLModels.TriggerRule)
            .filter_by(
                trigger_key=TRIGGER_KEY_ALERT_RULE,
                signal_family=signal_family,
                enabled=True,
                is_deleted=False,
            )
            .order_by(
                SQLModels.TriggerRule.sort_order.asc(),
                SQLModels.TriggerRule.id.asc(),
            )
            .all()
        )
        matched_rows = []
        for row in rows:
            source_ids = parse_serialized_json(getattr(row, "source_ids_json", None), [])
            if not source_ids and row.source_template_id is not None:
                source_ids = [row.source_template_id]
            if source_id in source_ids:
                matched_rows.append(row)
        return matched_rows

    def get_enabled_trigger_rules(self, *, trigger_key: str, source_id: int | None):
        ensure_alert_rule_tables()
        rows = (
            self.db.query(SQLModels.TriggerRule)
            .filter_by(trigger_key=trigger_key, enabled=True, is_deleted=False)
            .order_by(SQLModels.TriggerRule.sort_order.asc(), SQLModels.TriggerRule.id.asc())
            .all()
        )
        if source_id is None:
            return [row for row in rows if not parse_serialized_json(getattr(row, "source_ids_json", None), [])]
        matched_rows = []
        for row in rows:
            source_ids = parse_serialized_json(getattr(row, "source_ids_json", None), [])
            if not source_ids and row.source_template_id is not None:
                source_ids = [row.source_template_id]
            if source_id in source_ids:
                matched_rows.append(row)
        return matched_rows

    def resolve_trigger_delivery_target_ids(self, *, trigger_key: str, source_id: int | None):
        rows = self.get_enabled_trigger_rules(trigger_key=trigger_key, source_id=source_id)
        if not rows:
            return None
        target_ids: list[int] = []
        seen: set[int] = set()
        has_explicit_delivery_targets = False
        for row in rows:
            raw_target_ids = getattr(row, "delivery_target_ids_json", None)
            if raw_target_ids is None:
                continue
            has_explicit_delivery_targets = True
            for target_id in parse_serialized_json(raw_target_ids, []):
                target_id = int(target_id)
                if target_id in seen:
                    continue
                seen.add(target_id)
                target_ids.append(target_id)
        if not has_explicit_delivery_targets:
            return None
        return target_ids

    def resolve_source_delivery_target_ids(self, source_id: int | None) -> list[int] | None:
        if source_id is None:
            return None
        ensure_alert_rule_tables()
        rows = (
            self.db.query(SQLModels.TriggerRule)
            .filter_by(enabled=True, is_deleted=False)
            .all()
        )
        target_ids: list[int] = []
        seen: set[int] = set()
        for row in rows:
            source_ids = parse_serialized_json(getattr(row, "source_ids_json", None), [])
            if not source_ids and row.source_template_id is not None:
                source_ids = [row.source_template_id]
            if source_id not in source_ids:
                continue
            for target_id in parse_serialized_json(getattr(row, "delivery_target_ids_json", None), []):
                target_id = int(target_id)
                if target_id in seen:
                    continue
                seen.add(target_id)
                target_ids.append(target_id)
        return target_ids if target_ids else None

    def create_alert_incident(
        self,
        *,
        alert_rule_id: int,
        source_id: int | None,
        signal_family: str,
        matched_target: str,
        confidence: float,
        alert_level: str,
        camera_id: int | None,
        timestamp: float | None,
        dedupe_key: str,
        model_keys: dict[str, str | None],
    ) -> SQLModels.AlertIncident | None:
        ensure_alert_rule_tables()
        existing = (
            self.db.query(SQLModels.AlertIncident)
            .filter_by(
                run_id=DatabaseWorker.run_id,
                dedupe_key=dedupe_key,
                is_deleted=False,
            )
            .first()
        )
        if existing is not None:
            return existing

        incident_model = SQLModels.Incident(
            run_id=DatabaseWorker.run_id,
            incident_type=IncidentType.ALERT,
            status=IncidentStatus.UNCONFIRMED,
            camera_id=camera_id,
            zone_id=None,
            timestamp=timestamp,
            updated_by="system",
        )
        alert_model = SQLModels.AlertIncident(
            run_id=DatabaseWorker.run_id,
            alert_rule_id=alert_rule_id,
            source_template_id=source_id,
            signal_family=signal_family,
            matched_target=matched_target,
            confidence=confidence,
            alert_level=alert_level,
            title=build_alert_incident_title(signal_family, matched_target),
            model_keys_json=json.dumps(model_keys),
            dedupe_key=dedupe_key,
        )
        try:
            self.db.add(incident_model)
            self.db.flush()
            alert_model.incident_id = incident_model.id
            self.db.add(alert_model)
            self.db.commit()
            self.db.refresh(incident_model)
            self.db.refresh(alert_model)
            trigger_rule = self.db.query(SQLModels.TriggerRule).filter_by(id=alert_rule_id).first()
            delivery_target_ids = parse_serialized_json(
                getattr(trigger_rule, "delivery_target_ids_json", None),
                None,
            ) if trigger_rule is not None else None
            self.queue_trigger_notifications(
                incident_model,
                display_title=alert_model.title,
                source_id=source_id,
                alert_level=resolve_alert_level_label(alert_level),
                metadata={
                    "signal_family": signal_family,
                    "matched_target": matched_target,
                    "confidence": round(float(confidence), 3),
                },
                trigger_key=TRIGGER_KEY_ALERT_RULE,
                delivery_target_ids=delivery_target_ids,
            )
            return alert_model
        except SQLAlchemyError:
            self.db.rollback()
            logger.exception("Failed to create alert incident")
            return None

    def get_enabled_telegram_subscriptions(self):
        ensure_telegram_subscription_tables()
        return list_connector_endpoint_rows(
            self.db,
            connector_key=CONNECTOR_KEY_TELEGRAM,
            enabled_only=True,
        )

    def get_enabled_apple_message_subscriptions(self):
        ensure_apple_message_subscription_tables()
        return list_connector_endpoint_rows(
            self.db,
            connector_key=CONNECTOR_KEY_APPLE_MESSAGES,
            enabled_only=True,
        )

    def get_enabled_claude_api_connectors(self):
        ensure_claude_api_connector_tables()
        return list_connector_endpoint_rows(
            self.db,
            connector_key=CONNECTOR_KEY_CLAUDE_API,
            enabled_only=True,
        )

    def get_enabled_action_connectors(self):
        ensure_action_connector_tables()
        rows = []
        for connector_key in ACTION_CONNECTOR_KEYS:
            rows.extend(
                list_connector_endpoint_rows(
                    self.db,
                    connector_key=connector_key,
                    enabled_only=True,
                )
            )
        return sorted(rows, key=lambda row: row.id or 0)

    def filter_connector_rows_by_targets(self, rows, delivery_target_ids: list[int] | None):
        if delivery_target_ids is None:
            return rows
        target_ids = {int(item) for item in delivery_target_ids}
        return [row for row in rows if row.id in target_ids]

    def get_enabled_govee_endpoints(self):
        ensure_govee_connector_tables()
        return list_connector_endpoint_rows(
            self.db,
            connector_key=CONNECTOR_KEY_GOVEE,
            enabled_only=True,
        )
    def queue_trigger_notifications(
        self,
        incident_row: SQLModels.Incident,
        *,
        display_title: str | None = None,
        source_id: int | None = None,
        alert_level: str | None = None,
        metadata: dict | None = None,
        trigger_key: str | None = None,
        delivery_target_ids: list[int] | None = None,
    ) -> None:
        telegram_subscriptions = self.filter_connector_rows_by_targets(
            self.get_enabled_telegram_subscriptions(),
            delivery_target_ids,
        )
        apple_message_subscriptions = self.filter_connector_rows_by_targets(
            self.get_enabled_apple_message_subscriptions(),
            delivery_target_ids,
        )
        claude_api_connectors = self.filter_connector_rows_by_targets(
            self.get_enabled_claude_api_connectors(),
            delivery_target_ids,
        )
        action_connectors = self.filter_connector_rows_by_targets(
            self.get_enabled_action_connectors(),
            delivery_target_ids,
        )
        govee_endpoints = self.filter_connector_rows_by_targets(
            self.get_enabled_govee_endpoints(),
            delivery_target_ids,
        )
        if (
            not telegram_subscriptions
            and not apple_message_subscriptions
            and not claude_api_connectors
            and not action_connectors
            and not govee_endpoints
        ):
            return
        run_row = (
            self.db.query(SQLModels.Run)
            .filter_by(id=DatabaseWorker.run_id)
            .order_by(SQLModels.Run.id.desc())
            .first()
        )
        source_label = None
        if source_id is not None:
            source_row = self.get_source_row_by_id(source_id)
            source_label = source_row.label if source_row is not None else None
        occurred_at = None
        if incident_row.created_at is not None:
            occurred_at = incident_row.created_at.isoformat()
        elif incident_row.timestamp is not None:
            occurred_at = datetime.fromtimestamp(incident_row.timestamp).isoformat()
        trigger_text = build_trigger_notification_text(
            trigger_id=f"{incident_row.incident_type}-{incident_row.id}",
            trigger_type=str(incident_row.incident_type),
            display_title=display_title or str(incident_row.incident_type),
            run_identifier=run_row.run_identifier if run_row is not None else None,
            source_label=source_label,
            camera_id=incident_row.camera_id,
            alert_level=alert_level,
            occurred_at=occurred_at,
            metadata=metadata,
        )
        claude_payload = build_claude_trigger_payload(
            trigger_id=f"{incident_row.incident_type}-{incident_row.id}",
            trigger_type=str(trigger_key or incident_row.incident_type),
            trigger_text=trigger_text,
            display_title=display_title or str(incident_row.incident_type),
            run_identifier=run_row.run_identifier if run_row is not None else None,
            source_label=source_label,
            camera_id=incident_row.camera_id,
            alert_level=alert_level,
            occurred_at=occurred_at,
            metadata=metadata,
        )
        action_payloads_by_id = {}
        for row in action_connectors:
            try:
                config = validate_action_connector_config(get_connector_endpoint_config(row))
            except ValueError as exc:
                logger.warning("Skipping invalid action connector %s: %s", getattr(row, "id", None), exc)
                continue
            action_payloads_by_id[int(row.id)] = build_action_trigger_payload(
                connector_key=str(getattr(row, "connector_key", config["action_type"])),
                command=config["command"],
                target=config["target"],
                parameters=config["parameters"],
                trigger_id=f"{incident_row.incident_type}-{incident_row.id}",
                trigger_type=str(trigger_key or incident_row.incident_type),
                display_title=display_title or str(incident_row.incident_type),
                run_identifier=run_row.run_identifier if run_row is not None else None,
                source_label=source_label,
                camera_id=incident_row.camera_id,
                alert_level=alert_level,
                occurred_at=occurred_at,
                metadata=metadata,
            )
        if telegram_subscriptions:
            media = self.resolve_telegram_media(
                run_identifier=run_row.run_identifier if run_row is not None else None,
                camera_id=incident_row.camera_id,
                source_id=source_id,
            )
            queue_telegram_trigger_notifications(
                telegram_subscriptions,
                trigger_text=trigger_text,
                trigger_id=f"{incident_row.incident_type}-{incident_row.id}",
                trigger_type=str(trigger_key or incident_row.incident_type),
                media=media,
            )
        if apple_message_subscriptions:
            queue_apple_message_trigger_notifications(
                apple_message_subscriptions,
                trigger_text=trigger_text,
            )
        if claude_api_connectors:
            queue_claude_api_trigger_notifications(
                claude_api_connectors,
                payload=claude_payload,
            )
        if action_payloads_by_id:
            queue_action_trigger_notifications(
                action_connectors,
                payloads_by_id=action_payloads_by_id,
            )
        if govee_endpoints:
            queue_govee_trigger_actions(
                govee_endpoints,
                trigger_text=trigger_text,
            )

    def resolve_telegram_media(
        self,
        *,
        run_identifier: str | None,
        camera_id: int | None,
        source_id: int | None,
    ) -> dict:
        if not run_identifier:
            return {}
        camera_key = camera_id
        if camera_key is None and source_id is not None:
            source_row = self.get_source_row_by_id(source_id)
            if source_row is not None and source_row.kind == "webcam":
                try:
                    camera_key = int(source_row.source_value)
                except (TypeError, ValueError):
                    camera_key = None
        if camera_key is None:
            camera_key = 0
        frame_row = (
            self.db.query(SQLModels.Frame)
            .filter_by(run_id=DatabaseWorker.run_id, cam_id=camera_key, is_deleted=False)
            .order_by(SQLModels.Frame.id.desc())
            .first()
        )
        if frame_row is None:
            return {}
        candidate_path = str(getattr(frame_row, "path", "") or "").strip()
        if not candidate_path:
            return {}
        resolved = Path(candidate_path).expanduser()
        if not resolved.is_absolute():
            resolved = (Path.cwd() / resolved).resolve()
        if not resolved.exists():
            return {}
        return {"frame_snapshot_path": str(resolved)}

    def maybe_create_detector_alerts(self, track: DataModels.TrackInstance):
        source_id = self.get_source_template_id_for_camera(track.cam_id)
        if source_id is None:
            return
        confidence = track.confidence
        if confidence is None:
            # Confirmed PERSON/BAG tracks are still valid detector matches even when
            # the tracker/ReID handoff omits the original detector score.
            confidence = 1.0 if (track.confirmed or track.real_id is not None) else 0.0
        confidence = float(confidence)
        matched_target = str(track.clss or "").strip().upper()
        if not matched_target:
            return
        rules = self.get_enabled_alert_rules(
            source_id=source_id,
            signal_family=ALERT_SIGNAL_FAMILY_DETECTOR,
        )
        if not rules:
            return
        model_keys = self.resolve_model_keys_for_source(source_id)
        for rule in rules:
            if str(rule.target_key).strip().upper() != matched_target:
                continue
            if confidence < float(rule.min_confidence):
                continue
            dedupe_key = (
                f"detector:{rule.id}:{source_id}:{matched_target}:{track.track_id}"
            )
            self.create_alert_incident(
                alert_rule_id=rule.id,
                source_id=source_id,
                signal_family=ALERT_SIGNAL_FAMILY_DETECTOR,
                matched_target=matched_target,
                confidence=confidence,
                alert_level=rule.alert_level,
                camera_id=track.cam_id,
                timestamp=track.timestamp,
                dedupe_key=dedupe_key,
                model_keys={
                    "detector": model_keys.get(MODEL_STAGE_DETECTOR),
                },
            )

    def maybe_create_anomaly_alerts(self, event: DataModels.AnomalyEvent):
        source_id = (
            event.source_id
            if event.source_id is not None
            else self.get_source_template_id_for_camera(event.camera_id)
        )
        if source_id is None:
            return
        confidence = float(event.score or 0.0)
        cutoff_score = max(1, min(10, int(round(confidence * 10)) or 1))
        model_keys = {
            "anomaly_stage_1": event.stage_1_model_key,
            "anomaly_stage_2": event.stage_2_model_key or event.model_key,
        }
        for signal_family, candidates in (
            (
                ALERT_SIGNAL_FAMILY_ANOMALY_OBJECT,
                event.visible_items,
            ),
            (
                ALERT_SIGNAL_FAMILY_ANOMALY_ACTIVITY,
                event.visible_activities,
            ),
        ):
            rules = self.get_enabled_alert_rules(
                source_id=source_id,
                signal_family=signal_family,
            )
            if not rules:
                continue
            normalized_candidates = {
                str(candidate).strip().lower(): str(candidate).strip()
                for candidate in candidates
                if str(candidate).strip()
            }
            if not normalized_candidates:
                continue
            for rule in rules:
                normalized_target = str(rule.target_key).strip().lower()
                matched_target = normalized_candidates.get(normalized_target)
                if matched_target is None:
                    continue
                anomaly_cutoff = getattr(rule, "anomaly_cutoff", None)
                if anomaly_cutoff is None:
                    metadata = parse_serialized_json(getattr(rule, "metadata_json", None)) or {}
                    if isinstance(metadata, dict):
                        anomaly_cutoff = metadata.get("anomaly_cutoff")
                if anomaly_cutoff is None:
                    anomaly_cutoff = 6
                if cutoff_score < int(anomaly_cutoff):
                    continue
                dedupe_key = f"anomaly:{rule.id}:{event.event_id}:{normalized_target}"
                self.create_alert_incident(
                    alert_rule_id=rule.id,
                    source_id=source_id,
                    signal_family=signal_family,
                    matched_target=matched_target,
                    confidence=confidence,
                    alert_level=rule.alert_level,
                    camera_id=event.camera_id,
                    timestamp=None,
                    dedupe_key=dedupe_key,
                    model_keys=model_keys,
                )

    # Create functions

    def create_camera_recording(self, camera: DataModels.Camera):
        assert DatabaseWorker.run_id is not None, "run id is not set"
        if not self.get(SQLModels.Camera, camera.cam_id):
            self.create_camera(camera)
        cam_recording = SQLModels.CameraRecording(
            cam_id=camera.cam_id,
            run_id=DatabaseWorker.run_id,
            cam_recording_path=camera.recording_path,
            source_kind=camera.camera_type,
            source_template_id=camera.source_template_id,
            upload_id=camera.upload_id,
            total_frames=camera.total_frames,
            start_timestamp=camera.start_timestamp,
            start_datetime=camera.start_datetime,
            width=camera.width,
            height=camera.height,
        )
        self.create(cam_recording)

    def create_camera(self, camera: DataModels.Camera):
        camera = SQLModels.Camera(
            id=camera.cam_id,
            name=camera.name,
            tasks=camera.tasks,
            cam_ip_address=camera.source,
            camera_loc_x=camera.x_loc,
            camera_loc_y=camera.y_loc,
        )
        self.create(camera)

    def publish_run(self, run: DataModels.Run):
        existing = (
            self.db.query(SQLModels.Run)
            .filter_by(run_identifier=run.run_identifier, is_deleted=False)
            .first()
        )
        if existing is not None:
            if run.start_timestamp is not None and existing.start_timestamp is None:
                existing.start_timestamp = run.start_timestamp
            if run.start_datetime is not None and existing.start_datetime is None:
                existing.start_datetime = run.start_datetime
            if run.output_dir and not existing.output_dir:
                existing.output_dir = run.output_dir
            updated = self.update(existing)
            assert updated is not None, "failed to update existing run"
            DatabaseWorker.run_id = updated.id
            self._maybe_reset_for_run()
            return

        run_row = SQLModels.Run(
            run_identifier=run.run_identifier,
            start_timestamp=run.start_timestamp,
            start_datetime=run.start_datetime,
            output_dir=run.output_dir,
        )
        run_row = self.create(run_row)
        assert run_row is not None, "failed to create run"
        DatabaseWorker.run_id = run_row.id
        self._maybe_reset_for_run()

    def create_bag(self, id: int):
        bag = SQLModels.Bag(id=id, run_id=DatabaseWorker.run_id)
        self.create(bag)

    def create_bag_instance(self, track: DataModels.TrackInstance):
        assert track.real_id is not None

        if track.real_id not in self.confirmed_bags:
            self.create_bag(track.real_id)
            self.confirmed_bags.add(track.real_id)

        bag_instance = SQLModels.BagInstance(
            run_id=DatabaseWorker.run_id,
            bag_id=track.real_id,
            track_id=track.track_id,
            cam_id=track.cam_id,
            zone_id=track.zone_id,
            bbox=track.bbox,
            datetime=datetime.fromtimestamp(track.timestamp),
            timestamp=track.timestamp,
        )
        self.create(bag_instance)

    def create_person(self, id: int):
        person = SQLModels.Person(
            id=id,
            run_id=DatabaseWorker.run_id,
        )
        self.create(person)

    def create_person_instance(self, track: DataModels.TrackInstance):
        assert track.real_id is not None

        if track.real_id not in self.confirmed_persons:
            self.create_person(track.real_id)
            self.confirmed_persons.add(track.real_id)

        person_instance = SQLModels.PersonInstance(
            run_id=DatabaseWorker.run_id,
            person_id=track.real_id,
            track_id=track.track_id,
            cam_id=track.cam_id,
            zone_id=track.zone_id,
            bbox=track.bbox,
            feature_id=track.feature_id,
            timestamp=track.timestamp,
            datetime=datetime.fromtimestamp(track.timestamp),
            frame_id=track.frame_id,
        )
        self.create(person_instance)

    def create_incident(self, incident):
        incident_model = SQLModels.Incident(
            id=incident.id,
            run_id=DatabaseWorker.run_id,
            incident_type=incident.incident_type,
            status=incident.status,
            timestamp=incident.timestamp,
            camera_id=incident.cam_id,
            zone_id=incident.zone_id,
        )
        incident_row = self.create(incident_model)
        if incident_row is None:
            logger.error(f"Failed to create incident {incident.id}")
            return
        for entity in incident.entities.entities:
            role = incident.entities.roles[entity.id]
            if entity.clss == DetectorClasses.BAG:
                self.create_incident_bag_mapping(incident_row.id, entity.id, role)
            elif entity.clss == DetectorClasses.PERSON:
                self.create_incident_person_mapping(incident_row.id, entity.id, role)
            else:
                logger.error(f"Unknown entity class {entity.clss}")
                return
        self.queue_trigger_notifications(
            incident_row,
            source_id=self.get_source_template_id_for_camera(incident.cam_id),
            trigger_key="unattended_bag_trigger" if incident.incident_type == IncidentType.UNATTENDED_BAG else None,
            delivery_target_ids=self.resolve_trigger_delivery_target_ids(
                trigger_key="unattended_bag_trigger",
                source_id=self.get_source_template_id_for_camera(incident.cam_id),
            ) if incident.incident_type == IncidentType.UNATTENDED_BAG else None,
        )

    def create_incident_person_mapping(
        self, incident_id: int, person_id: int, role: str
    ):
        mapping = SQLModels.IncidentPersonMapping(
            incident_id=incident_id,
            person_id=person_id,
            role=role,
        )
        self.create(mapping)

    def create_incident_bag_mapping(self, incident_id: int, bag_id: int, role: str):
        mapping = SQLModels.IncidentBagMapping(
            incident_id=incident_id,
            bag_id=bag_id,
            role=role,
        )
        self.create(mapping)

    def create_frame(self, frame: DataModels.Frame, frame_id: int):
        assert DatabaseWorker.run_id is not None, "run id is not set"
        frame = SQLModels.Frame(
            run_id=DatabaseWorker.run_id,
            cam_id=frame.cam_id,
            frame_id=frame_id,
            path=frame.save_path,
            timestamp=frame.timestamp,
            datetime=datetime.fromtimestamp(frame.timestamp),
        )
        self.create(frame)

    def create_journey_node(self, node: DataModels.JourneyNode):
        track_instance = node.track_instance
        assert track_instance.real_id is not None

        node_model = SQLModels.JourneyNode(
            run_id=DatabaseWorker.run_id,
            crop_bbox=track_instance.bbox,
            camera_id=node.cam_id,
            zone_id=node.zone_id,
            start_timestamp=node.start_timestamp,
            stop_timestamp=None,
        )
        node_row = self.create(node_model)
        if node_row is None:
            logger.error("Failed to create JourneyNode")
            return

        if track_instance.clss == DetectorClasses.PERSON:
            self.create_person_journey_mapping(node_row.id, track_instance.real_id)
        elif track_instance.clss == DetectorClasses.BAG:
            self.create_bag_journey_mapping(node_row.id, track_instance.real_id)
        else:
            logger.error(
                f"Unknown class in JourneyNode's track ({track_instance.clss})"
            )
            return
        return node_row.id

    def create_person_journey_mapping(self, node_id: int, person_id: int):
        person_journey_model = SQLModels.PersonJourneyMapping(
            person_id=person_id,
            journey_node_id=node_id,
        )
        self.create(person_journey_model)

    def create_bag_journey_mapping(self, node_id: int, bag_id: int):
        person_journey_model = SQLModels.BagJourneyMapping(
            bag_id=bag_id,
            journey_node_id=node_id,
        )
        self.create(person_journey_model)

    def create_person_bag_mapping(self, bag_id: int, owner_id: int):
        person_bag_model = SQLModels.PersonBagMapping(
            person_id=owner_id,
            bag_id=bag_id,
        )
        self.create(person_bag_model)

    def create_poi_result(self, result: DataModels.POIResult):
        search_row = self.get(SQLModels.POISearch, result.search_id)
        if search_row is None:
            logger.error(f"Search with id {result.search_id} not found")
            return
        result_model = SQLModels.POISearchResult(
            run_id=DatabaseWorker.run_id,
            person_ids=result.ids,
        )
        result_row = self.create(result_model)
        if result_row is None:
            logger.error("Failed to create POISearchResult")
            return

        mapping = SQLModels.POIResultMapping(
            result_id=result_row.id,
            search_id=search_row.id,
        )
        self.create(mapping)

    def create_anomaly_event(self, event: DataModels.AnomalyEvent):
        existing = (
            self.db.query(SQLModels.AnomalyEvent)
            .filter_by(
                run_id=DatabaseWorker.run_id,
                event_key=event.event_id,
                is_deleted=False,
            )
            .first()
        )
        if existing is not None:
            return None
        anomaly_model = SQLModels.AnomalyEvent(
            run_id=DatabaseWorker.run_id,
            source_template_id=event.source_id,
            camera_id=event.camera_id,
            frame_id=event.frame_id,
            event_key=event.event_id,
            model_key=event.model_key,
            stage_1_model_key=event.stage_1_model_key,
            stage_2_model_key=event.stage_2_model_key,
            category=event.category,
            title=event.title,
            score=event.score,
            reasoning=event.reasoning,
            visible_items_json=json.dumps(event.visible_items),
            visible_activities_json=json.dumps(event.visible_activities),
            asset_refs_json=json.dumps(
                [asset.model_dump() for asset in event.asset_references]
            ),
        )
        return self.create(anomaly_model)

    def create_incident_from_anomaly_event(self, event: DataModels.AnomalyEvent):
        source_id = (
            event.source_id
            if event.source_id is not None
            else self.get_source_template_id_for_camera(event.camera_id)
        )
        incident_model = SQLModels.Incident(
            run_id=DatabaseWorker.run_id,
            incident_type=IncidentType.ANOMALY,
            status=IncidentStatus.UNCONFIRMED,
            camera_id=event.camera_id,
            zone_id=None,
            timestamp=None,
            updated_by="system",
        )
        incident_row = self.create(incident_model)
        if incident_row is None:
            return
        delivery_target_ids = self.resolve_trigger_delivery_target_ids(
            trigger_key="anomaly_event_trigger",
            source_id=source_id,
        )
        if delivery_target_ids is None:
            delivery_target_ids = self.resolve_source_delivery_target_ids(source_id)
        self.queue_trigger_notifications(
            incident_row,
            display_title=event.title or event.category,
            source_id=source_id,
            metadata={
                "category": event.category,
                "score": round(float(event.score or 0.0), 3),
            },
            trigger_key="anomaly_event_trigger",
            delivery_target_ids=delivery_target_ids,
        )

    # Update Functions

    def resolve_incident(self, incident_id: int):
        incident = self.get(SQLModels.Incident, incident_id)
        if incident and incident.status == IncidentStatus.UNCONFIRMED:
            update_model = SQLModels.IncidentUpdate(
                incident_id=incident_id,
                run_id=DatabaseWorker.run_id,
                new_status=IncidentStatus.PENDING_RESOLVE,
                old_status=incident.status,
                updated_by="system",
            )
            update = self.create(update_model)
            if update is not None:
                incident.status = update.new_status
                incident.current_update = update_model.id
                self.update(incident)
        else:
            logger.error(f"Incident with id {incident_id} not found.")

    def end_journey_node(self, node: DataModels.JourneyNode, node_id: int):
        node_row = self.get(SQLModels.JourneyNode, node_id)
        if node_row:
            node_row.stop_timestamp = node.stop_timestamp
            self.update(node_row)
        else:
            logger.error(f"Journey node with id {node_id} not found.")

    # Publish functions

    def publish_reid_data(self, tracks: dict[str, list[DataModels.TrackInstance]]):
        if DatabaseWorker.run_id is None:
            logger.warning("Skipping reid database publish because run id is not set")
            return
        self._maybe_reset_for_run()
        self.source_rows_by_id.clear()
        with self.SessionLocal() as self.db:
            for clss in tracks:
                for track in tracks[clss]:
                    self.maybe_create_detector_alerts(track)
                    if clss == DetectorClasses.PERSON:
                        self.create_person_instance(track)
                    elif clss == DetectorClasses.BAG:
                        self.create_bag_instance(track)

    def publish_journey_data(
        self,
        new_nodes: list[DataModels.JourneyNode],
        completed_nodes: list[DataModels.JourneyNode],
    ):
        self._maybe_reset_for_run()
        with self.SessionLocal() as self.db:
            for node in completed_nodes:
                track = node.track_instance
                node_id = self.journey_node_ids[track.clss][track.real_id].get(
                    track.cam_id
                )
                if node_id is None:
                    logger.error(
                        f"Node id not found for track {track.clss} {track.real_id} in cam {track.cam_id}"
                    )
                    continue
                self.end_journey_node(node, node_id)
                del self.journey_node_ids[track.clss][track.real_id][track.cam_id]
                if not self.journey_node_ids[track.clss][track.real_id]:
                    del self.journey_node_ids[track.clss][track.real_id]
            for node in new_nodes:
                node_id = self.create_journey_node(node)
                track = node.track_instance
                self.journey_node_ids[track.clss][track.real_id][track.cam_id] = node_id

    def publish_poi_data(self, poi_results: list[DataModels.POIResult]):
        with self.SessionLocal() as self.db:
            for poi_result in poi_results:
                self.create_poi_result(poi_result)

    def publish_bag_owner_pairs(self, pairs: list[tuple[int, int]]):
        with self.SessionLocal() as self.db:
            for bag_id, owner_id in pairs:
                self.create_person_bag_mapping(bag_id, owner_id)

    def publish_frames(self, frames: list[DataModels.Frame], frame_id: int):
        self._maybe_reset_for_run()
        with self.SessionLocal() as self.db:
            for frame in frames:
                self.create_frame(frame, frame_id)

    def publish_detector_logs(self, frames: list[DataModels.Frame], frame_id: int):
        if DatabaseWorker.run_id is None:
            logger.warning("Skipping detector model logs because run id is not set")
            return
        self._maybe_reset_for_run()
        self.source_rows_by_id.clear()
        self.source_template_ids_by_camera_id.clear()
        with self.SessionLocal() as self.db:
            for frame in frames:
                self.create_detector_model_log(frame, frame_id)

    def publish_incidents(self, new_incidents: list, resolved_incidents: list):
        with self.SessionLocal() as self.db:
            for incident in new_incidents:
                self.create_incident(incident)
            for incident in resolved_incidents:
                self.resolve_incident(incident.id)

    def publish_run_info(self, run: DataModels.Run):
        with self.SessionLocal() as self.db:
            self.publish_run(run)
            for camera in run.cameras:
                self.create_camera_recording(camera)

    def create_loitering_incident(self, incident) -> None:
        incident_row = SQLModels.Incident(
            run_id=DatabaseWorker.run_id,
            incident_type=incident.incident_type,
            status=incident.status,
            timestamp=incident.first_seen,
            camera_id=incident.cam_id,
            zone_id=incident.zone_id,
        )
        incident_row = self.create(incident_row)
        if incident_row is None:
            logger.error(f"Failed to create loitering incident for person {incident.person_id}")
            return
        self.create_incident_person_mapping(incident_row.id, incident.person_id, incident.role)
        self.queue_trigger_notifications(
            incident_row,
            source_id=self.get_source_template_id_for_camera(incident.cam_id),
            trigger_key="loitering_trigger",
            delivery_target_ids=self.resolve_trigger_delivery_target_ids(
                trigger_key="loitering_trigger",
                source_id=self.get_source_template_id_for_camera(incident.cam_id),
            ),
        )

    def publish_loitering_incidents(self, incidents: list) -> None:
        if not incidents:
            return
        with self.SessionLocal() as self.db:
            for incident in incidents:
                self.create_loitering_incident(incident)

    def publish_anomaly_data(self, anomaly_events: list[DataModels.AnomalyEvent]):
        self._maybe_reset_for_run()
        with self.SessionLocal() as self.db:
            for event in anomaly_events:
                created_event = self.create_anomaly_event(event)
                if created_event is not None:
                    self.create_anomaly_model_logs(event)
                    self.create_incident_from_anomaly_event(event)
                    self.maybe_create_anomaly_alerts(event)

    def publish_anomaly_evaluation_log(
        self,
        *,
        source_id: int | None,
        camera_id: int | None,
        frame_id: int | None,
        stage_1_model_key: str | None,
        stage_2_model_key: str | None,
        score: float,
        category: str | None,
        reasoning: str | None,
        promoted: bool,
    ):
        if DatabaseWorker.run_id is None:
            logger.warning("Skipping anomaly model logs because run id is not set")
            return
        self._maybe_reset_for_run()
        self.source_rows_by_id.clear()
        self.source_template_ids_by_camera_id.clear()
        with self.SessionLocal() as self.db:
            self.create_anomaly_evaluation_logs(
                source_id=source_id,
                camera_id=camera_id,
                frame_id=frame_id,
                stage_1_model_key=stage_1_model_key,
                stage_2_model_key=stage_2_model_key,
                score=score,
                category=category,
                reasoning=reasoning,
                promoted=promoted,
            )

    def check_for_resolutions(self, incidents: set | list):
        resolved_incidents = set()
        with self.SessionLocal() as self.db:
            for incident in incidents:
                db_incident = self.get(SQLModels.Incident, incident.id)
                if db_incident is not None:
                    if db_incident.status == "resolved":
                        resolved_incidents.add(incident)
        return resolved_incidents

    def publish_id_updates(self, id_updates: dict[str, dict[int, int]]):
        with self.SessionLocal() as self.db:
            person_updates = id_updates.get(DetectorClasses.PERSON, {})
            for temp_id, persistent_id in person_updates.items():
                updated_rows = []

                # Skip if no actual change
                if temp_id == persistent_id:
                    continue

                # Ensure the temporary record exists
                person = self.get(SQLModels.Person, temp_id)
                if not person:
                    logger.warning(
                        f"Person with temp_id {temp_id} not found for ID update."
                    )
                    continue

                # Create the permanent mapping record
                mapping = SQLModels.EntityIdMapping(
                    persistent_id=persistent_id,
                    temporary_id=temp_id,
                    entity_type=DetectorClasses.PERSON,
                )
                self.db.add(mapping)

                # Find all child records pointing to the temp_id and update them
                # to point to the persistent_id.
                fk_updates = self.update_person_foreign_keys(
                    temp_id, persistent_id
                )
                updated_rows.extend(fk_updates)

                # Check if the persistent_id already exists (merge vs. rename)
                if not self.get(SQLModels.Person, persistent_id):
                    # Create case: The persistent_id is new.
                    # Create a new person record with the persistent_id.
                    self.create_person(persistent_id)
                    self.confirmed_persons.add(persistent_id)
                self.delete(person)
                if temp_id in self.confirmed_persons:
                    self.confirmed_persons.remove(temp_id)

                self.batch_update(updated_rows)

            bag_updates = id_updates.get(DetectorClasses.BAG, {})
            for temp_id, persistent_id in bag_updates.items():
                updated_rows = []

                if temp_id == persistent_id:
                    continue

                bag = self.get(SQLModels.Bag, temp_id)
                if not bag:
                    logger.warning(f"Bag with temp_id {temp_id} not found for ID update.")
                    continue

                mapping = SQLModels.EntityIdMapping(
                    persistent_id=persistent_id,
                    temporary_id=temp_id,
                    entity_type=DetectorClasses.BAG,
                )
                self.db.add(mapping)

                fk_updates = self.update_bag_foreign_keys(temp_id, persistent_id)
                updated_rows.extend(fk_updates)

                if not self.get(SQLModels.Bag, persistent_id):
                    self.create_bag(persistent_id)
                    self.confirmed_bags.add(persistent_id)
                self.delete(bag)
                if temp_id in self.confirmed_bags:
                    self.confirmed_bags.remove(temp_id)

                self.batch_update(updated_rows)

    def update_person_foreign_keys(self, old_id: int, new_id: int):
        updated_rows = []
 
        person_instances = (
            self.db.query(SQLModels.PersonInstance).filter_by(person_id=old_id).all()
        )
        for person_instance in person_instances:
            person_instance.person_id = new_id
            updated_rows.append(person_instance)

        person_bag_mappings = (
            self.db.query(SQLModels.PersonBagMapping).filter_by(person_id=old_id).all()
        )
        for person_bag_mapping in person_bag_mappings:
            person_bag_mapping.person_id = new_id
            updated_rows.append(person_bag_mapping)

        person_incident_mappings = (
            self.db.query(SQLModels.IncidentPersonMapping)
            .filter_by(person_id=old_id)
            .all()
        )
        for person_incident_mapping in person_incident_mappings:
            person_incident_mapping.person_id = new_id
            updated_rows.append(person_incident_mapping)

        person_journey_mappings = (
            self.db.query(SQLModels.PersonJourneyMapping)
            .filter_by(person_id=old_id)
            .all()
        )
        for person_journey_mapping in person_journey_mappings:
            person_journey_mapping.person_id = new_id
            updated_rows.append(person_journey_mapping)

        return updated_rows

    def update_bag_foreign_keys(self, old_id: int, new_id: int):
        updated_rows = []
        bag_instances = (
            self.db.query(SQLModels.BagInstance).filter_by(bag_id=old_id).all()
        )
        for bag_instance in bag_instances:
            bag_instance.bag_id = new_id
            updated_rows.append(bag_instance)

        person_bag_mappings = (
            self.db.query(SQLModels.PersonBagMapping).filter_by(bag_id=old_id).all()
        )
        for person_bag_mapping in person_bag_mappings:
            person_bag_mapping.bag_id = new_id
            updated_rows.append(person_bag_mapping)

        bag_incident_mappings = (
            self.db.query(SQLModels.IncidentBagMapping).filter_by(bag_id=old_id).all()
        )
        for bag_incident_mapping in bag_incident_mappings:
            bag_incident_mapping.bag_id = new_id
            updated_rows.append(bag_incident_mapping)

        bag_journey_mappings = (
            self.db.query(SQLModels.BagJourneyMapping).filter_by(bag_id=old_id).all()
        )
        for bag_journey_mapping in bag_journey_mappings:
            bag_journey_mapping.bag_id = new_id
            updated_rows.append(bag_journey_mapping)

        return updated_rows
