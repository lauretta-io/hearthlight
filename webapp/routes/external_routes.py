import os
import queue
import shutil
import time
import logging
import asyncio
import json
from datetime import datetime
from importlib import import_module
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlparse
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from omegaconf import OmegaConf
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...shared.constants import (
    EntityType,
    ModuleNames,
    SHORT_SLEEP,
    VIDEO_EXTENSIONS,
)
from ...shared.database.database import SessionLocal, get_db, get_engine
from ...shared.models import DataModels, SQLModels
from ...shared.models.APIModels import (
    AdmissionStatus,
    AppearanceSettings,
    AppleMessageTriggerSubscription,
    AppleMessageTriggerTestResponse,
    AlertRule,
    AlertRuleOptionCatalog,
    ConnectorEndpoint,
    ConnectorZooEntry,
    ClaudeApiConnectorEndpoint,
    ClaudeApiConnectorTestResponse,
    AlgorithmEntityFeedItem,
    AlgorithmFeed,
    AssetReference as APIAssetReference,
    AnomalyPromptSettings,
    AnomalyEvent as APIAnomalyEvent,
    AlgorithmIncidentFeedItem,
    Camera,
    FeedEndpoint,
    FeedLocation,
    InputSource,
    ModelBinding,
    ModelHealth,
    ModelOptionCatalog,
    ModelResultLogPage,
    ModelRegistration,
    DemoTriggerFireRequest,
    DemoTriggerFireResponse,
    PluginBundleRecord,
    PluginComponentRecord,
    MountedModelStage,
    MODEL_BINDING_STAGES,
    MonitoringOverview,
    POISearch,
    ResourceSnapshot,
    ResourceEventRecord,
    RunSummary,
    SOURCE_KIND_CAMERA_URL,
    SOURCE_KIND_VIDEO_UPLOAD,
    SOURCE_KIND_WEBCAM,
    Status,
    TriggerRule,
    TriggerZooEntry,
    RuleSetZooEntry,
    TelegramTriggerSubscription,
    TelegramTriggerTestResponse,
    UploadResponse,
    UploadedMedia as UploadedMediaModel,
)
from ...shared.rabbit_messenger import (
    POISearchPublisher,
    RoutingKey,
    StatusConsumer,
    SystemMessagePublisher,
    get_connection,
)
from ...shared.utils.dependency_health import normalize_dependency_status
from ...shared.utils.backpressure import summarize_queue_backpressure
from ...shared.utils.alert_rules import (
    TRIGGER_KEY_ALERT_RULE,
    build_alert_rule_option_catalog,
    build_alert_rule_option_lookup,
    ensure_alert_rule_tables,
)
from ...shared.utils.apple_messages_notifications import (
    ensure_apple_message_subscription_tables,
    send_test_apple_message_trigger_message,
)
from ...shared.utils.claude_api_connector import (
    build_claude_trigger_payload,
    ensure_claude_api_connector_tables,
    send_claude_api_payload,
    validate_claude_api_config,
)
from ...shared.utils.connector_delivery_log import list_connector_delivery_events
from ...shared.utils.connector_endpoints import (
    CONNECTOR_KEY_APPLE_MESSAGES,
    CONNECTOR_KEY_CLAUDE_API,
    CONNECTOR_KEY_TELEGRAM,
    ensure_connector_endpoint_tables,
    get_connector_delivery_capabilities,
    get_connector_endpoint_config,
    MASKED_SECRET_VALUE,
    merge_connector_endpoint_secret_config,
    list_connector_endpoint_rows,
    redact_connector_endpoint_config,
    set_connector_endpoint_payload,
)
from ...shared.utils.telegram_notifications import (
    ensure_telegram_subscription_tables,
    send_test_telegram_trigger_message,
)
from ...shared.utils.trigger_connector_registry import load_connector_zoo, load_rule_set_zoo, load_trigger_zoo
from ...shared.utils.image import decode_base64
from ...shared.utils.input_sources import (
    build_runtime_camera_map,
    build_upload_filename,
    coerce_source_value,
    compute_sha256,
    configure_capture_timeouts,
    derive_source_error,
    derive_upload_lifecycle_state,
    format_supported_video_extensions,
    open_capture,
    probe_source_connection,
    source_requires_gpu,
    validate_uploaded_video_file,
)
from ...shared.utils.local_worker_runtime import (
    build_local_worker_url,
    is_hybrid_local_cpu_runtime,
    map_container_path_to_host,
)
from ...shared.utils.model_registry import (
    OPERATOR_MODEL_STAGES,
    build_default_bindings,
    build_model_health,
    build_model_display_name,
    build_model_option_catalog,
    build_runtime_binding_block,
    build_source_binding_overrides,
    build_effective_mounted_models,
    collect_required_mounted_models,
    ensure_mounted_model_key,
    get_registration,
    get_stage_field_name,
    load_registry_bundle,
    MODEL_BINDINGS_PATH,
    persist_mounted_models,
    normalize_binding_stage,
    resolve_bindings_for_source,
    sync_registry_bundle_to_db,
    validate_source_bindings,
)
from ...shared.utils.plugin_loader import (
    COMPONENT_TYPE_CONNECTOR,
    COMPONENT_TYPE_TRIGGER,
    load_plugin_catalog,
    sync_plugin_catalog_to_db,
)
from ...shared.utils.resource_monitor import (
    PersistedEvent,
    ResourceMonitor,
    collect_resource_snapshot,
    evaluate_admission,
    serialize_json,
    utc_now_iso,
)
from ...shared.utils.resource_drift import build_resource_drift
from ...shared.utils.monitoring_feed import (
    build_feed_endpoint_catalog,
    infer_run_status,
    normalize_feed_limit,
    parse_serialized_json,
)
from ...shared.utils.security import resolve_safe_child_path
from ...shared.utils.workspace_settings import (
    SETTING_KEY_APPEARANCE,
    get_workspace_setting_value,
    set_workspace_setting_value,
)
from ...shared.utils.system_state import (
    SystemStatus,
    derive_system_status,
    get_error_modules,
    normalize_module_status,
)
from .operations_routes import create_entity_id, create_incident_id, get_last_journey_node

external_router = APIRouter()
logger = logging.getLogger(__name__)

CONFIG_PATH = Path(os.environ.get("HEARTHLIGHT_CONFIG_PATH", "shared/configs/config.yaml"))
POI_CROP_DIR = Path(os.environ.get("POI_CROP_DIR", "shared/output/poi_crops"))
SOURCE_UPLOAD_DIR = Path(
    os.environ.get(
        "SOURCE_UPLOAD_DIR",
        str(CONFIG_PATH.parent.parent / "output" / "source_uploads"),
    )
)
SOURCE_PREVIEW_TIMEOUT_MS = int(
    os.environ.get("SOURCE_PREVIEW_TIMEOUT_MS", "5000")
)
SOURCE_PREVIEW_FRAME_DELAY_SECONDS = float(
    os.environ.get("SOURCE_PREVIEW_FRAME_DELAY_SECONDS", "0.1")
)
SOURCE_PREVIEW_JPEG_QUALITY = int(
    os.environ.get("SOURCE_PREVIEW_JPEG_QUALITY", "80")
)
MAX_POI_IMAGES = int(os.environ.get("POI_MAX_IMAGES", "10"))
MAX_UPLOAD_BYTES = int(os.environ.get("SOURCE_UPLOAD_MAX_BYTES", str(512 * 1024 * 1024)))
SOURCE_PROBE_TIMEOUT_MS = max(
    250, int(os.environ.get("SOURCE_PROBE_TIMEOUT_MS", "5000"))
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_WORKER_REQUEST_TIMEOUT_SECONDS = float(
    os.environ.get("HEARTHLIGHT_LOCAL_WORKER_REQUEST_TIMEOUT_SECONDS", "5.0")
)


def resolve_project_path(path_like: str | Path) -> Path:
    path = Path(path_like)
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def get_expected_module_names() -> list[str]:
    return [
        ModuleNames.INGESTOR,
        ModuleNames.ANOMALY,
    ]


def build_default_appearance_settings() -> AppearanceSettings:
    return AppearanceSettings(theme_key="fidelity-light")


def read_appearance_settings(db: Session) -> AppearanceSettings:
    payload = get_workspace_setting_value(
        db,
        SETTING_KEY_APPEARANCE,
        default=build_default_appearance_settings().model_dump(),
    )
    if not isinstance(payload, dict):
        payload = build_default_appearance_settings().model_dump()
    try:
        return AppearanceSettings.model_validate(payload)
    except Exception:
        return build_default_appearance_settings()


def write_appearance_settings(db: Session, payload: AppearanceSettings) -> AppearanceSettings:
    settings = AppearanceSettings.model_validate(payload)
    set_workspace_setting_value(
        db,
        SETTING_KEY_APPEARANCE,
        settings.model_dump(),
    )
    db.commit()
    return read_appearance_settings(db)


def build_host_upload_path(upload_path: str | None) -> str | None:
    if not upload_path:
        return None
    return map_container_path_to_host(upload_path)


def get_local_worker_health() -> dict:
    if not is_hybrid_local_cpu_runtime():
        return {
            "status": "not-applicable",
            "runtime": "docker",
            "workers": {},
        }
    try:
        with urllib_request.urlopen(
            build_local_worker_url("/healthz"),
            timeout=LOCAL_WORKER_REQUEST_TIMEOUT_SECONDS,
        ) as response:
            return json.load(response)
    except Exception:
        logger.warning("Failed to query local worker health", exc_info=True)
        return {
            "status": "unavailable",
            "runtime": "hybrid-local-cpu",
            "workers": {
                module_name: {
                    "running": False,
                    "pid": None,
                    "reason": "local CPU workers not started",
                }
                for module_name in get_expected_module_names()
            },
        }


def require_local_worker_ready() -> dict:
    health = get_local_worker_health()
    if health.get("status") == "ready":
        return health
    workers = health.get("workers") or {}
    reasons = [
        str(details.get("reason") or "").strip()
        for details in workers.values()
        if isinstance(details, dict) and str(details.get("reason") or "").strip()
    ]
    reason = reasons[0] if reasons else "local CPU workers not started"
    raise HTTPException(status_code=409, detail=reason)


def probe_source_via_local_worker(
    kind: str,
    source_value,
    *,
    upload_path: str | None = None,
) -> str | None:
    request_body = json.dumps(
        {
            "kind": kind,
            "source_value": source_value,
            "upload_path": build_host_upload_path(upload_path),
        }
    ).encode("utf-8")
    request = urllib_request.Request(
        build_local_worker_url("/probe"),
        data=request_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(
            request,
            timeout=LOCAL_WORKER_REQUEST_TIMEOUT_SECONDS,
        ) as response:
            payload = json.load(response)
    except Exception:
        logger.warning("Failed to probe source via local worker", exc_info=True)
        return "source validation failed on local worker"
    if payload.get("ok", False):
        return None
    detail = str(payload.get("detail") or "").strip()
    return detail or "source validation failed on local worker"


ANOMALY_TEXT_PROMPT_PATH = Path(
    resolve_project_path(
        os.environ.get("ANOMALY_TEXT_PROMPT_PATH", "shared/prompts/prompt_v2.yaml")
    )
)
ANOMALY_PROMPT_CONFIG_PATH = Path(
    resolve_project_path(
        os.environ.get("ANOMALY_PROMPT_CONFIG_PATH", "shared/prompts/stage2_prompt_config.yaml")
    )
)
ANOMALY_TYPE_PROMPT_PATH = Path(
    resolve_project_path(
        os.environ.get("ANOMALY_TYPE_PROMPT_PATH", "shared/prompts/anomaly_list.yaml")
    )
)
STANDARD_ANOMALY_PROMPT_CONFIG_PATH = resolve_project_path("shared/prompts/stage2_prompt_config.yaml")
STANDARD_ANOMALY_TEXT_PROMPT_PATH = resolve_project_path("shared/prompts/prompt_v2.yaml")
STANDARD_ANOMALY_TYPE_PROMPT_PATH = resolve_project_path("shared/prompts/anomaly_list.yaml")
MODULE_RESTART_DELAY_SEC = float(os.environ.get("MODULE_RESTART_DELAY_SEC", "1.0"))
REQUIRE_GPU_FOR_START = os.environ.get("WEBAPP_REQUIRE_GPU", "false").lower() in {
    "1",
    "true",
    "yes",
}

cfg = None
feature_extractor = None
poi_publisher = None
system_publisher = None
status_consumer = None
resource_monitor = None
state_lock = Lock()

status = SystemStatus.IDLE
frame_id = None
total_frames = None
module_status = {
    ModuleNames.INGESTOR: DataModels.Status.IDLE,
    ModuleNames.ANOMALY: DataModels.Status.IDLE,
}
module_metrics = {}
module_runtime_details = {}
run_id = None


def get_default_module_status():
    return {
        ModuleNames.INGESTOR: DataModels.Status.IDLE,
        ModuleNames.ANOMALY: DataModels.Status.IDLE,
    }


def get_resource_thresholds():
    return {
        "cpu_percent": float(os.environ.get("RESOURCE_CPU_THRESHOLD_PERCENT", "95")),
        "memory_percent": float(
            os.environ.get("RESOURCE_MEMORY_THRESHOLD_PERCENT", "95")
        ),
        "disk_percent": float(os.environ.get("RESOURCE_DISK_THRESHOLD_PERCENT", "95")),
        "gpu_percent": float(os.environ.get("RESOURCE_GPU_THRESHOLD_PERCENT", "95")),
        "gpu_memory_percent": float(
            os.environ.get("RESOURCE_GPU_MEMORY_THRESHOLD_PERCENT", "95")
        ),
    }


def get_resource_drift_thresholds():
    return {
        "cpu_percent_delta": float(
            os.environ.get("RESOURCE_CPU_DRIFT_THRESHOLD_PERCENT", "20")
        ),
        "memory_percent_delta": float(
            os.environ.get("RESOURCE_MEMORY_DRIFT_THRESHOLD_PERCENT", "10")
        ),
        "disk_percent_delta": float(
            os.environ.get("RESOURCE_DISK_DRIFT_THRESHOLD_PERCENT", "5")
        ),
        "gpu_utilization_delta": float(
            os.environ.get("RESOURCE_GPU_DRIFT_THRESHOLD_PERCENT", "25")
        ),
        "gpu_memory_delta_mb": float(
            os.environ.get("RESOURCE_GPU_MEMORY_DRIFT_THRESHOLD_MB", "512")
        ),
    }


def check_database_dependency():
    from ...shared.database.database import get_engine

    engine = get_engine()
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def check_rabbitmq_dependency():
    channel = None
    connection = None
    try:
        channel, connection = get_connection(
            "resource_health_probe",
            RoutingKey.STATUS_MESSAGE,
            False,
        )
    finally:
        if connection is not None and connection.is_open:
            connection.close()


def check_ffmpeg_dependency():
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg binary not found")


def collect_dependency_status():
    checks = {}
    for name, checker in (
        ("database", check_database_dependency),
        ("rabbitmq", check_rabbitmq_dependency),
        ("ffmpeg", check_ffmpeg_dependency),
    ):
        try:
            checker()
            checks[name] = (True, None)
        except Exception as exc:
            checks[name] = (False, str(exc))
    return normalize_dependency_status(checks)


def merge_hybrid_operator_status(
    module_state: dict[str, str] | None,
    dependency_state: dict[str, dict] | None,
    local_worker_health: dict | None = None,
) -> dict[str, str]:
    """Keep top-level operator status aligned with local worker health in hybrid mode."""
    merged = dict(module_state or {})
    if not is_hybrid_local_cpu_runtime():
        return merged
    workers = (local_worker_health or {}).get("workers") or {}
    for module_name in (ModuleNames.INGESTOR, ModuleNames.ANOMALY):
        details = workers.get(module_name)
        if isinstance(details, dict):
            merged[module_name] = (
                DataModels.Status.RUNNING
                if bool(details.get("running"))
                else DataModels.Status.IDLE
            )
    dependency_state = dependency_state or {}
    for module_name in (ModuleNames.INGESTOR, ModuleNames.ANOMALY):
        dependency = dependency_state.get(module_name.lower())
        if not isinstance(dependency, dict):
            continue
        if dependency.get("status") == "ok":
            merged[module_name] = DataModels.Status.RUNNING
        elif dependency.get("status") == "error":
            merged[module_name] = DataModels.Status.ERROR
    return merged


def reset_runtime_state(clear_run: bool):
    global frame_id
    global total_frames
    global module_status
    global module_metrics
    global module_runtime_details
    global run_id

    frame_id = None
    total_frames = None
    module_status = get_default_module_status()
    module_metrics = {}
    module_runtime_details = {}
    if clear_run:
        run_id = None


def get_cfg():
    global cfg
    if cfg is not None:
        return cfg
    if not CONFIG_PATH.exists():
        raise HTTPException(
            status_code=503, detail=f"runtime config not found at {CONFIG_PATH}"
        )
    try:
        cfg = OmegaConf.load(CONFIG_PATH)
    except Exception as exc:
        logger.exception("Failed to load runtime config")
        raise HTTPException(
            status_code=503, detail="failed to load runtime config"
        ) from exc
    return cfg


def clone_cfg():
    return OmegaConf.create(OmegaConf.to_container(get_cfg(), resolve=False))


def get_feature_extractor():
    global feature_extractor
    if feature_extractor is not None:
        return feature_extractor
    try:
        feature_extractor_cls = getattr(
            import_module("hearthlight_model_zoo.feature_extractors"),
            "FeatureExtractor",
        )
        feature_extractor = feature_extractor_cls(
            get_cfg().feature_extractor.model_name, device="cpu"
        )
    except ModuleNotFoundError as exc:
        logger.exception("Feature extractor package is unavailable")
        raise HTTPException(
            status_code=503,
            detail="feature extractor dependencies are unavailable in this runtime",
        ) from exc
    except Exception as exc:
        logger.exception("Failed to initialize feature extractor")
        raise HTTPException(
            status_code=503, detail="failed to initialize feature extractor"
        ) from exc
    return feature_extractor


def get_poi_publisher():
    global poi_publisher
    if poi_publisher is None:
        try:
            poi_publisher = POISearchPublisher()
        except Exception as exc:
            logger.exception("Failed to initialize POI publisher")
            raise HTTPException(
                status_code=503, detail="poi publisher unavailable"
            ) from exc
    return poi_publisher


def get_system_publisher():
    global system_publisher
    if system_publisher is None:
        try:
            system_publisher = SystemMessagePublisher()
        except Exception as exc:
            logger.exception("Failed to initialize system publisher")
            raise HTTPException(
                status_code=503, detail="system publisher unavailable"
            ) from exc
    return system_publisher


def get_status_consumer():
    global status_consumer
    if status_consumer is None:
        try:
            status_consumer = StatusConsumer()
            status_consumer.start()
        except Exception as exc:
            logger.exception("Failed to initialize status consumer")
            raise HTTPException(
                status_code=503, detail="status consumer unavailable"
            ) from exc
    return status_consumer


def get_upload_dir() -> Path:
    upload_dir = SOURCE_UPLOAD_DIR.resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def persist_resource_snapshot(snapshot: dict):
    with SessionLocal() as db:
        db.add(
            SQLModels.ResourceSnapshot(
                cpu_percent=snapshot.get("cpu_percent"),
                memory_percent=snapshot.get("memory_percent"),
                disk_percent=snapshot.get("disk_percent"),
                gpu_json=serialize_json(snapshot.get("gpus")),
                module_status_json=serialize_json(snapshot.get("module_status")),
                model_health_json=serialize_json(snapshot.get("model_health")),
                admission_json=serialize_json(snapshot.get("admission")),
                drift_json=serialize_json(snapshot.get("drift")),
            )
        )
        db.commit()


def log_resource_event(event: PersistedEvent):
    try:
        with SessionLocal() as db:
            db.add(
                SQLModels.ResourceEvent(
                    event_type=event.event_type,
                    severity=event.severity,
                    message=event.message,
                    metadata_json=serialize_json(event.metadata),
                )
            )
            db.commit()
    except Exception:
        logger.exception("Failed to persist resource event")


def get_previous_resource_snapshot(db: Session):
    row = (
        db.query(SQLModels.ResourceSnapshot)
        .order_by(SQLModels.ResourceSnapshot.id.desc())
        .first()
    )
    if row is None:
        return None
    return {
        "cpu_percent": row.cpu_percent,
        "memory_percent": row.memory_percent,
        "disk_percent": row.disk_percent,
        "gpus": parse_serialized_json(row.gpu_json) or [],
        "updated_at": row.created_at.isoformat() if row.created_at is not None else None,
    }


def build_live_resource_snapshot(db: Session) -> dict:
    source_rows = get_active_source_rows(db)
    enabled_source_rows = [row for row in source_rows if row.enabled]
    registry_bundle = get_registry_bundle(db, source_rows=source_rows)
    snapshot = collect_resource_snapshot(
        module_status.copy(),
        disk_path=get_upload_dir(),
    )
    snapshot["drift"] = build_resource_drift(
        snapshot,
        get_previous_resource_snapshot(db),
        thresholds=get_resource_drift_thresholds(),
    )
    local_worker_health = get_local_worker_health() if is_hybrid_local_cpu_runtime() else None
    snapshot["dependency_status"] = collect_dependency_status()
    snapshot["module_status"] = merge_hybrid_operator_status({
        ModuleNames.WEBAPP: DataModels.Status.RUNNING,
        **module_status.copy(),
    }, snapshot["dependency_status"], local_worker_health)
    snapshot["module_metrics"] = module_metrics.copy()
    snapshot["model_health"] = build_model_health(
        registry_bundle,
        has_gpu=bool(snapshot.get("gpus")),
    )
    admission = evaluate_admission(
        snapshot,
        requires_gpu=REQUIRE_GPU_FOR_START
        or selected_sources_require_gpu(
            registry_bundle,
            enabled_source_rows,
            has_gpu=bool(snapshot.get("gpus")),
        ),
        enabled_source_count=len(enabled_source_rows),
        module_status=snapshot.get("module_status", {}),
        thresholds=get_resource_thresholds(),
    )
    source_errors = build_enabled_source_errors(source_rows, db)
    if is_hybrid_local_cpu_runtime():
        if local_worker_health.get("status") != "ready":
            workers = local_worker_health.get("workers") or {}
            reasons = [
                str(details.get("reason") or "").strip()
                for details in workers.values()
                if isinstance(details, dict) and str(details.get("reason") or "").strip()
            ]
            reason = reasons[0] if reasons else "local CPU workers not started"
            if admission.get("allowed", True):
                admission["allowed"] = False
                admission["reason"] = reason
    binding_errors = build_enabled_source_binding_errors(
        registry_bundle,
        enabled_source_rows,
        snapshot["model_health"],
        has_gpu=bool(snapshot.get("gpus")),
    )
    if binding_errors:
        source_errors.extend(binding_errors)
    if source_errors:
        admission["source_errors"] = source_errors
        if admission.get("allowed", True):
            admission["allowed"] = False
            admission["reason"] = source_errors[0]
    snapshot["admission"] = admission
    return snapshot


def build_live_resource_snapshot_with_session():
    with SessionLocal() as db:
        return build_live_resource_snapshot(db)


def get_resource_monitor():
    global resource_monitor
    if resource_monitor is None or not resource_monitor.is_alive():
        resource_monitor = ResourceMonitor(
            snapshot_supplier=build_live_resource_snapshot_with_session,
            persistence_callback=persist_resource_snapshot,
        )
        resource_monitor.start()
    return resource_monitor


def get_current_resource_snapshot(db: Session) -> dict:
    monitor = get_resource_monitor()
    snapshot = monitor.get_snapshot()
    if snapshot is None:
        snapshot = build_live_resource_snapshot(db)
    else:
        source_rows = get_active_source_rows(db)
        enabled_source_rows = [row for row in source_rows if row.enabled]
        registry_bundle = get_registry_bundle(db, source_rows=source_rows)
        local_worker_health = get_local_worker_health() if is_hybrid_local_cpu_runtime() else None
        snapshot["dependency_status"] = collect_dependency_status()
        snapshot["drift"] = build_resource_drift(
            snapshot,
            get_previous_resource_snapshot(db),
            thresholds=get_resource_drift_thresholds(),
        )
        snapshot["module_status"] = merge_hybrid_operator_status({
            ModuleNames.WEBAPP: DataModels.Status.RUNNING,
            **module_status.copy(),
        }, snapshot["dependency_status"], local_worker_health)
        snapshot["module_metrics"] = module_metrics.copy()
        snapshot["model_health"] = build_model_health(
            registry_bundle,
            has_gpu=bool(snapshot.get("gpus")),
        )
        snapshot["admission"] = evaluate_admission(
            snapshot,
            requires_gpu=REQUIRE_GPU_FOR_START
            or selected_sources_require_gpu(
                registry_bundle,
                enabled_source_rows,
                has_gpu=bool(snapshot.get("gpus")),
            ),
            enabled_source_count=len(enabled_source_rows),
            module_status=snapshot.get("module_status", {}),
            thresholds=get_resource_thresholds(),
        )
        source_errors = build_enabled_source_errors(source_rows, db)
        if is_hybrid_local_cpu_runtime():
            if local_worker_health.get("status") != "ready":
                workers = local_worker_health.get("workers") or {}
                reasons = [
                    str(details.get("reason") or "").strip()
                    for details in workers.values()
                    if isinstance(details, dict) and str(details.get("reason") or "").strip()
                ]
                reason = reasons[0] if reasons else "local CPU workers not started"
                if snapshot["admission"].get("allowed", True):
                    snapshot["admission"]["allowed"] = False
                    snapshot["admission"]["reason"] = reason
        binding_errors = build_enabled_source_binding_errors(
            registry_bundle,
            enabled_source_rows,
            snapshot["model_health"],
            has_gpu=bool(snapshot.get("gpus")),
        )
        if binding_errors:
            source_errors.extend(binding_errors)
        if source_errors:
            snapshot["admission"]["source_errors"] = source_errors
            if snapshot["admission"].get("allowed", True):
                snapshot["admission"]["allowed"] = False
                snapshot["admission"]["reason"] = source_errors[0]
    return snapshot


def get_latest_run_frame_id(db: Session) -> int | None:
    if run_id is None:
        return None
    run_row = db.query(SQLModels.Run).filter_by(run_identifier=run_id).first()
    if run_row is None:
        return None
    latest = (
        db.query(func.max(SQLModels.Frame.frame_id))
        .filter(
            SQLModels.Frame.run_id == run_row.id,
            SQLModels.Frame.is_deleted.is_(False),
        )
        .scalar()
    )
    if latest is None:
        return None
    try:
        return int(latest)
    except (TypeError, ValueError):
        return None


def shutdown_external_resources():
    global feature_extractor
    global poi_publisher
    global system_publisher
    global status_consumer
    global resource_monitor

    if resource_monitor is not None:
        resource_monitor.stop()
        resource_monitor.join(timeout=2)
        resource_monitor = None
    if status_consumer is not None:
        status_consumer.stop()
        status_consumer.join(timeout=2)
        status_consumer = None
    if poi_publisher is not None:
        poi_publisher.close()
        poi_publisher = None
    if system_publisher is not None:
        system_publisher.close()
        system_publisher = None
    feature_extractor = None


def get_active_source_rows(db: Session):
    ensure_source_template_columns(db)
    return (
        db.query(SQLModels.InputSourceTemplate)
        .filter_by(is_deleted=False)
        .order_by(
            SQLModels.InputSourceTemplate.sort_order.asc(),
            SQLModels.InputSourceTemplate.id.asc(),
        )
        .all()
    )


def ensure_source_template_columns(db: Session) -> None:
    existing = {
        row[0]
        for row in db.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'control'
                  AND table_name = 'input_source_template'
                """
            )
        ).all()
    }
    if "process_every_n_frames" not in existing:
        db.execute(
            text(
                """
                ALTER TABLE control.input_source_template
                ADD COLUMN process_every_n_frames INTEGER NOT NULL DEFAULT 1
                """
            )
        )
        db.commit()


def get_registry_bundle(
    db: Session | None = None,
    *,
    source_rows: list | None = None,
):
    bundle = load_registry_bundle()
    if db is None:
        return bundle
    try:
        ensure_plugin_tables()
        sync_plugin_catalog_to_db(
            db,
            bundle.get("plugin_catalog") or load_plugin_catalog(),
            SQLModels,
        )
        synced_source_rows = source_rows if source_rows is not None else get_active_source_rows(db)
        sync_registry_bundle_to_db(
            db,
            bundle,
            SQLModels,
            source_rows=synced_source_rows,
        )
        db.commit()
        for source_row in synced_source_rows:
            if getattr(source_row, "id", None) is not None:
                db.refresh(source_row)
    except Exception:
        db.rollback()
        logger.exception("Failed to mirror model registry metadata into control schema")
    return bundle


def ensure_plugin_tables() -> None:
    SQLModels.Base.metadata.create_all(
        bind=get_engine(),
        tables=[
            SQLModels.PluginBundle.__table__,
            SQLModels.PluginComponent.__table__,
        ],
        checkfirst=True,
    )


def _build_plugin_component_lookup_from_bundle(bundle: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    plugin_catalog = bundle.get("plugin_catalog") or load_plugin_catalog()
    lookup: dict[str, dict[str, dict[str, Any]]] = {}
    for component in plugin_catalog.get("components", []):
        component_type = str(component.get("component_type") or "").strip()
        component_key = str(component.get("component_key") or "").strip()
        if not component_type or not component_key:
            continue
        lookup.setdefault(component_type, {})[component_key] = component
    return lookup


def build_plugin_bundle_responses(db: Session) -> list[PluginBundleRecord]:
    ensure_plugin_tables()
    rows = (
        db.query(SQLModels.PluginBundle)
        .filter_by(is_deleted=False)
        .order_by(SQLModels.PluginBundle.plugin_key.asc())
        .all()
    )
    return [
        PluginBundleRecord(
            plugin_key=row.plugin_key,
            label=row.label,
            version=row.version,
            provider=row.provider,
            description=row.description or "",
            enabled_by_default=bool(row.enabled_by_default),
            manifest_path=row.manifest_path,
            manifest_fingerprint=row.manifest_fingerprint,
            load_status=row.load_status,
            load_error=row.load_error,
        )
        for row in rows
    ]


def build_plugin_component_responses(db: Session, *, plugin_key: str | None = None) -> list[PluginComponentRecord]:
    ensure_plugin_tables()
    query = db.query(SQLModels.PluginComponent).filter_by(is_deleted=False)
    if plugin_key:
        query = query.filter_by(plugin_key=plugin_key)
    rows = query.order_by(
        SQLModels.PluginComponent.component_type.asc(),
        SQLModels.PluginComponent.component_key.asc(),
    ).all()
    return [
        PluginComponentRecord(
            plugin_key=row.plugin_key,
            component_key=row.component_key,
            component_type=row.component_type,
            stage=row.stage,
            category=row.category,
            source_path=row.source_path,
            metadata=parse_serialized_json(row.metadata_json) or {},
            availability_status=row.availability_status,
            load_error=row.load_error,
        )
        for row in rows
    ]


def get_upload_rows_by_id(db: Session, upload_ids: list[int]):
    if not upload_ids:
        return {}
    rows = (
        db.query(SQLModels.UploadedMedia)
        .filter(
            SQLModels.UploadedMedia.id.in_(upload_ids),
            SQLModels.UploadedMedia.is_deleted.is_(False),
        )
        .all()
    )
    return {row.id: row for row in rows}


def get_source_row_by_id(source_id: int, db: Session):
    source_row = (
        db.query(SQLModels.InputSourceTemplate)
        .filter_by(id=source_id, is_deleted=False)
        .first()
    )
    if source_row is None:
        raise HTTPException(status_code=404, detail="source not found")
    return source_row


def sync_upload_lifecycle_states(
    db: Session,
    *,
    source_rows: list | None = None,
    active_upload_ids: set[int] | None = None,
):
    if source_rows is None:
        source_rows = get_active_source_rows(db)
    attached_upload_ids = {
        row.upload_id for row in source_rows if row.upload_id is not None
    }
    active_upload_ids = active_upload_ids or set()
    upload_rows = (
        db.query(SQLModels.UploadedMedia)
        .filter_by(is_deleted=False)
        .all()
    )
    for upload_row in upload_rows:
        upload_row.lifecycle_state = derive_upload_lifecycle_state(
            is_deleted=bool(upload_row.is_deleted),
            is_attached=upload_row.id in attached_upload_ids,
            is_enabled=upload_row.id in active_upload_ids,
        )


def db_upload_to_api(upload_row: SQLModels.UploadedMedia | None):
    if upload_row is None:
        return None
    return UploadedMediaModel(
        id=upload_row.id,
        original_filename=upload_row.original_filename,
        stored_path=upload_row.stored_path,
        checksum_sha256=upload_row.checksum_sha256,
        size_bytes=upload_row.size_bytes,
        lifecycle_state=upload_row.lifecycle_state,
    )


def coerce_source_value_for_api(source_row: SQLModels.InputSourceTemplate):
    if source_row.source_value is None:
        return None
    if source_row.kind == SOURCE_KIND_WEBCAM:
        try:
            return int(source_row.source_value)
        except (TypeError, ValueError):
            return source_row.source_value
    return source_row.source_value


def format_source_value_for_query(source_value: str | int | None) -> str:
    if source_value is None:
        return ""
    return str(source_value)


def resolve_preview_source_value(
    source_row: SQLModels.InputSourceTemplate,
    db: Session,
):
    preview_candidates = resolve_preview_source_candidates(source_row, db)
    return preview_candidates[0][0]


def get_preview_recording_path(
    source_row: SQLModels.InputSourceTemplate,
    db: Session,
) -> str | None:
    recording_rows = get_run_recordings_by_source_id(db)
    recording_row = recording_rows.get(source_row.id)
    if (
        recording_row is not None
        and recording_row.cam_recording_path
        and Path(recording_row.cam_recording_path).exists()
    ):
        return recording_row.cam_recording_path
    return None


def is_local_preview_source(source_value: str | int | None) -> bool:
    if not isinstance(source_value, str):
        return False
    parsed = urlparse(source_value)
    if parsed.scheme:
        return False
    return Path(source_value).exists()


def resolve_preview_source_candidates(
    source_row: SQLModels.InputSourceTemplate,
    db: Session,
) -> list[tuple[str | int, bool]]:
    upload_path = None
    if source_row.upload_id is not None:
        upload_row = get_upload_rows_by_id(db, [source_row.upload_id]).get(source_row.upload_id)
        upload_path = upload_row.stored_path if upload_row is not None else None

    candidates: list[tuple[str | int, bool]] = []
    if source_row.kind != SOURCE_KIND_VIDEO_UPLOAD:
        try:
            direct_source = coerce_source_value(
                source_row.kind,
                source_row.source_value,
                upload_path=upload_path,
            )
            candidates.append((direct_source, False))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    recording_path = get_preview_recording_path(source_row, db)
    if recording_path is not None:
        candidates.append((recording_path, True))

    if source_row.kind == SOURCE_KIND_VIDEO_UPLOAD:
        try:
            upload_source = coerce_source_value(
                source_row.kind,
                source_row.source_value,
                upload_path=upload_path,
            )
            candidates.append((upload_source, True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    normalized_candidates: list[tuple[str | int, bool]] = []
    seen = set()
    for candidate, is_local_file in candidates:
        cache_key = str(candidate)
        if cache_key in seen:
            continue
        seen.add(cache_key)
        normalized_candidates.append(
            (candidate, is_local_file or is_local_preview_source(candidate))
        )

    if not normalized_candidates:
        raise HTTPException(status_code=404, detail="preview source is unavailable")

    return normalized_candidates


def encode_preview_frame(frame) -> bytes | None:
    success, encoded = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), SOURCE_PREVIEW_JPEG_QUALITY],
    )
    if not success:
        return None
    return encoded.tobytes()


def get_run_recordings_by_source_id(db: Session):
    if run_id is None:
        return {}
    run_row = db.query(SQLModels.Run).filter_by(run_identifier=run_id).first()
    if run_row is None:
        return {}
    recordings = (
        db.query(SQLModels.CameraRecording)
        .filter_by(run_id=run_row.id)
        .order_by(SQLModels.CameraRecording.id.asc())
        .all()
    )
    result = {}
    for recording in recordings:
        if recording.source_template_id is not None:
            result[recording.source_template_id] = recording
    return result


def derive_source_state(
    source_row: SQLModels.InputSourceTemplate,
    recording: SQLModels.CameraRecording | None,
    resource_snapshot: dict,
    source_error: str | None = None,
):
    if not source_row.enabled:
        return "disabled"
    if source_error:
        return "failed"
    if status == SystemStatus.ERROR:
        return "failed"
    if status == SystemStatus.STOPPING:
        return "stopping"
    if status == SystemStatus.INITIALIZING:
        return "initializing"
    if status == SystemStatus.RUNNING:
        if (
            source_row.kind == SOURCE_KIND_VIDEO_UPLOAD
            and recording is not None
            and recording.total_frames is not None
            and frame_id is not None
            and frame_id >= recording.total_frames
        ):
            return "completed"
        return "running"
    return "idle"


def build_input_source_response(
    source_row: SQLModels.InputSourceTemplate,
    upload_row: SQLModels.UploadedMedia | None,
    recording: SQLModels.CameraRecording | None,
    resource_snapshot: dict,
    current_frame_override: int | None = None,
):
    current_frame = current_frame_override if current_frame_override is not None else frame_id
    current_total = recording.total_frames if recording is not None else None
    effective_error = build_effective_source_error(source_row, upload_row)
    if (
        current_total is not None
        and current_frame is not None
        and current_frame > current_total
    ):
        current_frame = current_total
    return InputSource(
        id=source_row.id,
        kind=source_row.kind,
        label=source_row.label,
        tasks=list(source_row.tasks),
        enabled=source_row.enabled,
        order=source_row.sort_order,
        source_value=coerce_source_value_for_api(source_row),
        upload_id=source_row.upload_id,
        upload=db_upload_to_api(upload_row),
        process_every_n_frames=max(1, int(getattr(source_row, "process_every_n_frames", 1) or 1)),
        detector_model_key=source_row.detector_model_key,
        tracker_model_key=source_row.tracker_model_key,
        reid_model_key=source_row.reid_model_key,
        anomaly_stage_1_model_key=source_row.anomaly_stage_1_model_key,
        anomaly_stage_2_model_key=source_row.anomaly_stage_2_model_key,
        state=derive_source_state(
            source_row,
            recording,
            resource_snapshot,
            source_error=effective_error,
        ),
        frames_processed=current_frame if source_row.enabled else None,
        total_frames=current_total,
        fps=None,
        last_error=effective_error,
        last_activity_at=resource_snapshot.get("updated_at"),
    )


def build_effective_source_error(
    source_row: SQLModels.InputSourceTemplate,
    upload_row: SQLModels.UploadedMedia | None,
):
    upload_path = upload_row.stored_path if upload_row is not None else None
    return source_row.last_error or derive_source_error(
        kind=source_row.kind,
        enabled=source_row.enabled,
        upload_id=source_row.upload_id,
        upload_path=upload_path,
        upload_exists=Path(upload_path).exists() if upload_path else False,
        upload_lifecycle_state=(
            upload_row.lifecycle_state if upload_row is not None else None
        ),
    )


def build_source_responses(db: Session, resource_snapshot: dict):
    source_rows = get_active_source_rows(db)
    upload_rows = get_upload_rows_by_id(
        db, [row.upload_id for row in source_rows if row.upload_id is not None]
    )
    recordings = get_run_recordings_by_source_id(db)
    current_frame_override = (
        get_latest_run_frame_id(db) if is_hybrid_local_cpu_runtime() else None
    )
    return [
        build_input_source_response(
            row,
            upload_rows.get(row.upload_id),
            recordings.get(row.id),
            resource_snapshot,
            current_frame_override=current_frame_override,
        )
        for row in source_rows
    ]


def build_enabled_source_errors(source_rows: list[SQLModels.InputSourceTemplate], db: Session):
    upload_rows = get_upload_rows_by_id(
        db, [row.upload_id for row in source_rows if row.upload_id is not None]
    )
    errors = []
    for source_row in source_rows:
        if not source_row.enabled:
            continue
        effective_error = build_effective_source_error(
            source_row,
            upload_rows.get(source_row.upload_id),
        )
        if effective_error:
            errors.append(f"{source_row.label}: {effective_error}")
    return errors


def build_enabled_source_binding_errors(
    bundle: dict,
    source_rows: list[SQLModels.InputSourceTemplate],
    model_health: dict[str, dict],
    *,
    has_gpu: bool | None = None,
):
    defaults = build_default_bindings(bundle, has_gpu=has_gpu)
    errors = []
    for source_row in source_rows:
        errors.extend(validate_source_bindings(bundle, source_row, defaults))
        resolved = resolve_bindings_for_source(source_row, defaults)
        for stage, model_key in resolved.items():
            if not model_key:
                errors.append(f"{source_row.label}: no {stage} model is selected")
                continue
            health = model_health.get(model_key)
            if health is None:
                errors.append(f"{source_row.label}: {stage} model {model_key} is not registered")
                continue
            if not health.get("healthy", False):
                detail = health.get("detail") or "model is unavailable"
                errors.append(f"{source_row.label}: {stage} model {model_key} is unhealthy: {detail}")
    return errors


def selected_sources_require_gpu(
    bundle: dict,
    source_rows: list[SQLModels.InputSourceTemplate],
    *,
    has_gpu: bool | None = None,
) -> bool:
    defaults = build_default_bindings(bundle, has_gpu=has_gpu)
    for source_row in source_rows:
        resolved = resolve_bindings_for_source(source_row, defaults)
        for stage, model_key in resolved.items():
            registration = get_registration(bundle, stage, model_key)
            if registration and registration.get("requires_gpu"):
                return True
    return False


def build_model_registration_responses(bundle: dict):
    registrations = []
    for stage, stage_models in bundle.get("models", {}).items():
        if stage not in OPERATOR_MODEL_STAGES:
            continue
        for model_key, registration in stage_models.items():
            registrations.append(
                ModelRegistration(
                    model_key=model_key,
                    display_name=build_model_display_name(stage, model_key, registration),
                    plugin_key=registration.get("plugin_key"),
                    stage=stage,
                    adapter=registration.get("adapter"),
                    artifact_ref=registration.get("artifact_ref"),
                    runtime=dict(registration.get("runtime") or {}),
                    capabilities=dict(registration.get("capabilities") or {}),
                    healthcheck=dict(registration.get("healthcheck") or {}),
                    requires_gpu=bool(registration.get("requires_gpu")),
                    resource_profile=dict(registration.get("resource_profile") or {}),
                    source_path=registration.get("source_path"),
                )
            )
    registrations.sort(key=lambda item: (item.stage, item.model_key))
    return registrations


def build_model_binding_responses(
    bundle: dict,
    source_rows: list[SQLModels.InputSourceTemplate],
    *,
    has_gpu: bool | None = None,
):
    defaults = build_default_bindings(bundle, has_gpu=has_gpu)
    component_lookup = _build_plugin_component_lookup_from_bundle(bundle)
    bindings = [
        ModelBinding(
            stage=stage,
            model_key=defaults.get(stage),
            binding_scope="default",
            resolved=(
                defaults.get(stage) in component_lookup.get("model", {})
                if defaults.get(stage)
                else True
            ),
            unavailable_reason=(
                None
                if not defaults.get(stage) or defaults.get(stage) in component_lookup.get("model", {})
                else f"model plugin component {defaults.get(stage)} is unavailable"
            ),
        )
        for stage in sorted(OPERATOR_MODEL_STAGES)
    ]
    for source_row in source_rows:
        overrides = build_source_binding_overrides(source_row)
        for stage, model_key in overrides.items():
            if model_key:
                bindings.append(
                    ModelBinding(
                        stage=stage,
                        model_key=model_key,
                        source_id=source_row.id,
                        binding_scope="source",
                        resolved=model_key in component_lookup.get("model", {}),
                        unavailable_reason=(
                            None
                            if model_key in component_lookup.get("model", {})
                            else f"model plugin component {model_key} is unavailable"
                        ),
                    )
                )
    return bindings


def build_mounted_model_stage_responses(bundle: dict):
    mounted_models = build_effective_mounted_models(bundle, bundle.get("mounted_models"))
    return [
        MountedModelStage(stage=stage, mounted_model_keys=list(mounted_models.get(stage) or []))
        for stage in sorted(OPERATOR_MODEL_STAGES)
    ]


def persist_model_bindings(defaults: dict[str, str | None]):
    bindings = {"defaults": dict(defaults)}
    MODEL_BINDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    OmegaConf.save(config=OmegaConf.create(bindings), f=str(MODEL_BINDINGS_PATH))


def validate_upload_references(db: Session, sources: list[InputSource]):
    upload_ids = sorted(
        {source.upload_id for source in sources if source.upload_id is not None}
    )
    upload_rows = get_upload_rows_by_id(db, upload_ids)
    missing = [upload_id for upload_id in upload_ids if upload_id not in upload_rows]
    if missing:
        missing_csv = ", ".join(str(upload_id) for upload_id in missing)
        raise HTTPException(
            status_code=400,
            detail=f"unknown or deleted uploads referenced: {missing_csv}",
        )
    return upload_rows


def replace_sources(db: Session, sources: list[InputSource]):
    existing_rows = get_active_source_rows(db)
    existing_by_id = {row.id: row for row in existing_rows}
    validate_upload_references(db, sources)
    bundle = get_registry_bundle(db, source_rows=existing_rows)
    mounted_models = build_effective_mounted_models(bundle, bundle.get("mounted_models"))

    seen_ids = set()
    persisted_rows = []
    for order, source in enumerate(sources):
        for stage in OPERATOR_MODEL_STAGES:
            model_key = getattr(source, get_stage_field_name(stage), None)
            if model_key is not None:
                registration = get_registration(bundle, stage, model_key)
                if registration is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"unknown {stage} model binding {model_key}",
                    )
                ensure_mounted_model_key(bundle, mounted_models, stage, model_key)
        row = existing_by_id.get(source.id) if source.id is not None else None
        if row is None:
            row = SQLModels.InputSourceTemplate()
            db.add(row)
        row.kind = source.kind
        row.label = source.label
        row.source_value = (
            None if source.kind == SOURCE_KIND_VIDEO_UPLOAD else str(source.source_value)
        )
        row.upload_id = source.upload_id
        row.tasks = list(source.tasks)
        row.enabled = source.enabled
        row.sort_order = order
        row.process_every_n_frames = max(1, int(source.process_every_n_frames or 1))
        row.detector_model_key = source.detector_model_key
        row.tracker_model_key = source.tracker_model_key
        row.reid_model_key = None
        row.anomaly_stage_1_model_key = source.anomaly_stage_1_model_key
        row.anomaly_stage_2_model_key = source.anomaly_stage_2_model_key
        row.last_error = None
        row.is_deleted = False
        row.deleted_at = None
        persisted_rows.append(row)
        if row.id is not None:
            seen_ids.add(row.id)

    db.flush()
    get_registry_bundle(db, source_rows=persisted_rows)
    persist_mounted_models(mounted_models)
    seen_ids.update(row.id for row in persisted_rows if row.id is not None)
    for row in existing_rows:
        if row.id not in seen_ids:
            row.is_deleted = True
            row.deleted_at = datetime.utcnow()
    ensure_alert_rule_tables()
    active_source_ids = {row.id for row in persisted_rows if row.id is not None}
    for alert_rule_row in db.query(SQLModels.TriggerRule).filter_by(is_deleted=False).all():
        referenced_source_ids = _deserialize_trigger_rule_source_ids(alert_rule_row)
        if not referenced_source_ids:
            referenced_source_ids = [alert_rule_row.source_template_id]
        if any(source_id not in active_source_ids for source_id in referenced_source_ids if source_id is not None):
            alert_rule_row.is_deleted = True
            alert_rule_row.deleted_at = datetime.utcnow()
    sync_upload_lifecycle_states(db, source_rows=persisted_rows, active_upload_ids=set())
    db.commit()
    for row in persisted_rows:
        db.refresh(row)
    return persisted_rows


def upsert_sources_and_build_response(db: Session, sources: list[InputSource]):
    replace_sources(db, sources)
    snapshot = get_current_resource_snapshot(db)
    return build_source_responses(db, snapshot)


def append_source(db: Session, source: InputSource):
    snapshot = get_current_resource_snapshot(db)
    existing_sources = build_source_responses(db, snapshot)
    new_source = InputSource(
        kind=source.kind,
        label=source.label,
        tasks=list(source.tasks),
        enabled=source.enabled,
        order=len(existing_sources),
        source_value=source.source_value,
        upload_id=source.upload_id,
        detector_model_key=source.detector_model_key,
        tracker_model_key=source.tracker_model_key,
        reid_model_key=source.reid_model_key,
        anomaly_stage_1_model_key=source.anomaly_stage_1_model_key,
        anomaly_stage_2_model_key=source.anomaly_stage_2_model_key,
    )
    return upsert_sources_and_build_response(db, [*existing_sources, new_source])


def _load_yaml_text(path: Path) -> str:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"prompt file not found at {path}")
    return path.read_text()


def _load_yaml_mapping(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = OmegaConf.load(path)
    if raw is None:
        return {}
    data = OmegaConf.to_container(raw, resolve=True)
    return data if isinstance(data, dict) else {}


def _normalize_anomaly_items(raw_items) -> list[dict[str, str]]:
    if raw_items is None:
        return []
    if not isinstance(raw_items, list):
        raise HTTPException(status_code=400, detail="anomaly_items must be a list")
    normalized = []
    seen = set()
    for entry in raw_items:
        item = ""
        if isinstance(entry, dict):
            item = str(entry.get("item") or "").strip()
        else:
            item = str(entry or "").strip()
        if not item:
            raise HTTPException(status_code=400, detail="anomaly item name cannot be empty")
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append({"item": item})
    return normalized


def _normalize_anomaly_behaviors(raw_behaviors) -> list[str]:
    if raw_behaviors is None:
        return []
    if not isinstance(raw_behaviors, list):
        raise HTTPException(status_code=400, detail="anomaly_behaviors must be a list")
    normalized = []
    seen = set()
    for entry in raw_behaviors:
        value = str(entry or "").strip()
        if not value:
            raise HTTPException(status_code=400, detail="anomaly behavior cannot be empty")
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(value)
    return normalized


def _read_stage2_prompt_config(
    config_path: Path,
    *,
    fallback_prompt_path: Path,
    fallback_type_path: Path,
) -> dict:
    config = _load_yaml_mapping(config_path)
    if not config:
        prompt_cfg = _load_yaml_mapping(fallback_prompt_path)
        type_cfg = _load_yaml_mapping(fallback_type_path)
        config = {
            "template": str(prompt_cfg.get("template") or "").strip(),
            "anomaly_items": [
                str(item).strip()
                for item in list(type_cfg.get("anomaly_object_list") or [])
                if str(item).strip()
            ],
            "anomaly_behaviors": [
                str(item).strip()
                for item in list(type_cfg.get("anomaly_activity_list") or [])
                if str(item).strip()
            ],
        }
    template = str(config.get("template") or "").strip()
    if not template:
        fallback_prompt_cfg = _load_yaml_mapping(fallback_prompt_path)
        template = str(fallback_prompt_cfg.get("template") or "").strip()
    return {
        "template": template,
        "anomaly_items": _normalize_anomaly_items(config.get("anomaly_items") or []),
        "anomaly_behaviors": _normalize_anomaly_behaviors(config.get("anomaly_behaviors") or []),
    }


def _build_anomaly_type_payload_from_config(config: dict) -> dict[str, list[str]]:
    anomaly_items = []
    for entry in config.get("anomaly_items", []):
        value = entry.get("item") if isinstance(entry, dict) else entry
        normalized = str(value or "").strip()
        if normalized:
            anomaly_items.append(normalized)
    return {
        "anomaly_object_list": anomaly_items,
        "anomaly_activity_list": [str(item).strip() for item in config.get("anomaly_behaviors", []) if str(item).strip()],
    }


def _serialize_prompt_yaml(template: str) -> str:
    return OmegaConf.to_yaml({"template": template.rstrip()}, resolve=True).rstrip() + "\n"


def _serialize_anomaly_type_yaml(config: dict) -> str:
    return (
        OmegaConf.to_yaml(
            {
                **_build_anomaly_type_payload_from_config(config),
                "anomaly_items": list(config.get("anomaly_items") or []),
                "anomaly_behaviors": list(config.get("anomaly_behaviors") or []),
            },
            resolve=True,
        ).rstrip()
        + "\n"
    )


def _build_anomaly_prompt_settings_response(
    config_path: Path,
    *,
    fallback_prompt_path: Path,
    fallback_type_path: Path,
) -> AnomalyPromptSettings:
    config = _read_stage2_prompt_config(
        config_path,
        fallback_prompt_path=fallback_prompt_path,
        fallback_type_path=fallback_type_path,
    )
    return AnomalyPromptSettings.model_validate(
        {
            "anomaly_items": config["anomaly_items"],
            "anomaly_behaviors": config["anomaly_behaviors"],
        }
    )


def _validate_prompt_settings_payload(payload: AnomalyPromptSettings):
    del payload


def read_anomaly_prompt_settings() -> AnomalyPromptSettings:
    return _build_anomaly_prompt_settings_response(
        ANOMALY_PROMPT_CONFIG_PATH,
        fallback_prompt_path=ANOMALY_TEXT_PROMPT_PATH,
        fallback_type_path=ANOMALY_TYPE_PROMPT_PATH,
    )


def read_standard_anomaly_prompt_settings() -> AnomalyPromptSettings:
    return _build_anomaly_prompt_settings_response(
        STANDARD_ANOMALY_PROMPT_CONFIG_PATH,
        fallback_prompt_path=STANDARD_ANOMALY_TEXT_PROMPT_PATH,
        fallback_type_path=STANDARD_ANOMALY_TYPE_PROMPT_PATH,
    )


def write_anomaly_prompt_settings(payload: AnomalyPromptSettings) -> AnomalyPromptSettings:
    _validate_prompt_settings_payload(payload)
    existing_config = _read_stage2_prompt_config(
        ANOMALY_PROMPT_CONFIG_PATH,
        fallback_prompt_path=ANOMALY_TEXT_PROMPT_PATH,
        fallback_type_path=ANOMALY_TYPE_PROMPT_PATH,
    )
    ANOMALY_TEXT_PROMPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ANOMALY_TYPE_PROMPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ANOMALY_PROMPT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "template": existing_config.get("template") or "",
        "anomaly_items": [item.item for item in payload.anomaly_items],
        "anomaly_behaviors": list(payload.anomaly_behaviors),
    }
    ANOMALY_PROMPT_CONFIG_PATH.write_text(
        OmegaConf.to_yaml(config, resolve=True).rstrip() + "\n"
    )
    ANOMALY_TEXT_PROMPT_PATH.write_text(_serialize_prompt_yaml(str(config["template"])))
    ANOMALY_TYPE_PROMPT_PATH.write_text(_serialize_anomaly_type_yaml(config))
    return read_anomaly_prompt_settings()


def get_alert_rule_rows(db: Session):
    ensure_alert_rule_tables()
    return (
        db.query(SQLModels.TriggerRule)
        .filter_by(
            trigger_key=TRIGGER_KEY_ALERT_RULE,
            is_deleted=False,
        )
        .order_by(
            SQLModels.TriggerRule.source_template_id.asc(),
            SQLModels.TriggerRule.sort_order.asc(),
            SQLModels.TriggerRule.id.asc(),
        )
        .all()
    )


def build_alert_rule_responses(db: Session):
    return [
        AlertRule(
            id=row.id,
            source_id=row.source_template_id,
            enabled=row.enabled,
            rule_label=row.rule_label,
            signal_family=row.signal_family,
            target_key=row.target_key,
            min_confidence=float(row.min_confidence),
            alert_level=row.alert_level,
            created_at=row.created_at.isoformat() if row.created_at is not None else None,
            updated_at=row.updated_at.isoformat() if row.updated_at is not None else None,
        )
        for row in get_alert_rule_rows(db)
    ]


def build_trigger_rule_responses(db: Session):
    ensure_alert_rule_tables()
    ensure_plugin_tables()
    source_rows = get_active_source_rows(db)
    bundle = get_registry_bundle(db, source_rows=source_rows)
    plugin_component_lookup = _build_plugin_component_lookup_from_bundle(bundle)
    trigger_components = plugin_component_lookup.get(COMPONENT_TYPE_TRIGGER, {})
    rows = (
        db.query(SQLModels.TriggerRule)
        .filter_by(is_deleted=False)
        .order_by(
            SQLModels.TriggerRule.trigger_key.asc(),
            SQLModels.TriggerRule.source_template_id.asc(),
            SQLModels.TriggerRule.sort_order.asc(),
            SQLModels.TriggerRule.id.asc(),
        )
        .all()
    )
    return [
        TriggerRule(
            id=row.id,
            trigger_key=row.trigger_key,
            source_id=row.source_template_id,
            source_ids=_deserialize_trigger_rule_source_ids(row),
            enabled=row.enabled,
            rule_label=row.rule_label,
            rule_kind=_deserialize_trigger_rule_kind(row),
            signal_family=row.signal_family,
            anomaly_target_kind=_deserialize_trigger_rule_anomaly_target_kind(row),
            target_key=row.target_key,
            min_confidence=float(row.min_confidence),
            anomaly_cutoff=_deserialize_trigger_rule_anomaly_cutoff(row),
            alert_level=row.alert_level,
            delivery_target_ids=parse_serialized_json(row.delivery_target_ids_json) or [],
            metadata=parse_serialized_json(row.metadata_json) or {},
            resolved=(
                _deserialize_trigger_rule_key(row) in trigger_components
            ),
            unavailable_reason=(
                None
                if _deserialize_trigger_rule_key(row) in trigger_components
                else f"trigger plugin component {_deserialize_trigger_rule_key(row)} is unavailable"
            ),
            created_at=row.created_at.isoformat() if row.created_at is not None else None,
            updated_at=row.updated_at.isoformat() if row.updated_at is not None else None,
        )
        for row in rows
    ]


def _deserialize_trigger_rule_source_ids(row: SQLModels.TriggerRule) -> list[int]:
    source_ids = parse_serialized_json(getattr(row, "source_ids_json", None)) or []
    if isinstance(source_ids, list):
        normalized: list[int] = []
        for item in source_ids:
            try:
                item_int = int(item)
            except (TypeError, ValueError):
                continue
            if item_int > 0 and item_int not in normalized:
                normalized.append(item_int)
        if normalized:
            return normalized
    if row.source_template_id:
        return [int(row.source_template_id)]
    return []


def _deserialize_trigger_rule_key(row: SQLModels.TriggerRule) -> str:
    return str(getattr(row, "trigger_key", "") or "").strip().lower()


def _deserialize_trigger_rule_kind(row: SQLModels.TriggerRule) -> str:
    value = str(getattr(row, "rule_kind", "") or "").strip().lower()
    if value in {"detector", "anomaly"}:
        return value
    if str(row.signal_family or "").startswith("anomaly_"):
        return "anomaly"
    return "detector"


def _deserialize_trigger_rule_anomaly_target_kind(row: SQLModels.TriggerRule) -> str | None:
    value = str(getattr(row, "anomaly_target_kind", "") or "").strip().lower()
    if value in {"object", "behavior"}:
        return value
    signal_family = str(row.signal_family or "").strip().lower()
    if signal_family == "anomaly_object":
        return "object"
    if signal_family == "anomaly_activity":
        return "behavior"
    return None


def _deserialize_trigger_rule_anomaly_cutoff(row: SQLModels.TriggerRule) -> int | None:
    value = getattr(row, "anomaly_cutoff", None)
    if value is None:
        metadata = parse_serialized_json(row.metadata_json) or {}
        if isinstance(metadata, dict):
            value = metadata.get("anomaly_cutoff")
    if value is None:
        return None
    try:
        value_int = int(value)
    except (TypeError, ValueError):
        return None
    return value_int if 1 <= value_int <= 10 else None


def build_alert_rule_options_response(db: Session) -> AlertRuleOptionCatalog:
    source_rows = get_active_source_rows(db)
    bundle = get_registry_bundle(db, source_rows=source_rows)
    try:
        anomaly_prompt_settings = read_anomaly_prompt_settings()
        anomaly_type_yaml = (
            OmegaConf.to_yaml(
                {
                    "anomaly_object_list": [item.item for item in anomaly_prompt_settings.anomaly_items],
                    "anomaly_activity_list": list(anomaly_prompt_settings.anomaly_behaviors),
                },
                resolve=True,
            ).rstrip()
            + "\n"
        )
    except HTTPException:
        anomaly_type_yaml = None
    snapshot = get_current_resource_snapshot(db)
    catalog = build_alert_rule_option_catalog(
        bundle=bundle,
        source_rows=source_rows,
        anomaly_type_yaml=anomaly_type_yaml,
        has_gpu=bool(snapshot.get("gpus")),
    )
    return AlertRuleOptionCatalog.model_validate(catalog)


def validate_alert_rules_payload(
    db: Session,
    rules: list[AlertRule],
) -> tuple[dict[int, SQLModels.InputSourceTemplate], dict[int, dict[str, dict]]]:
    source_rows = get_active_source_rows(db)
    source_by_id = {row.id: row for row in source_rows}
    option_catalog = build_alert_rule_options_response(db)
    option_lookup = build_alert_rule_option_lookup(option_catalog.model_dump())

    for rule in rules:
        if rule.source_id not in source_by_id:
            raise HTTPException(status_code=404, detail=f"source {rule.source_id} not found")
        source_signal_options = option_lookup.get(rule.source_id, {})
        signal_options = source_signal_options.get(rule.signal_family)
        if signal_options is None:
            raise HTTPException(
                status_code=400,
                detail=f"signal family {rule.signal_family} is unavailable for source {rule.source_id}",
            )
        if signal_options.get("unavailable_reason"):
            raise HTTPException(
                status_code=400,
                detail=signal_options["unavailable_reason"],
            )
        valid_targets = {
            str(option.get("key")).strip().lower()
            for option in signal_options.get("options", [])
        }
        if rule.target_key.strip().lower() not in valid_targets:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"invalid target '{rule.target_key}' for source {rule.source_id} "
                    f"and signal family {rule.signal_family}"
                ),
            )
    return source_by_id, option_lookup


def replace_alert_rules(db: Session, rules: list[AlertRule]):
    ensure_alert_rule_tables()
    existing_rows = get_alert_rule_rows(db)
    existing_by_id = {row.id: row for row in existing_rows}
    source_by_id, _ = validate_alert_rules_payload(db, rules)
    del source_by_id

    seen_ids = set()
    persisted_rows = []
    source_rule_counts: dict[int, int] = {}
    for rule in rules:
        row = existing_by_id.get(rule.id) if rule.id is not None else None
        if row is None:
            row = SQLModels.TriggerRule()
            db.add(row)
        source_order = source_rule_counts.get(rule.source_id, 0)
        source_rule_counts[rule.source_id] = source_order + 1
        row.trigger_key = TRIGGER_KEY_ALERT_RULE
        row.source_template_id = rule.source_id
        row.enabled = rule.enabled
        row.sort_order = source_order
        row.rule_label = rule.rule_label
        row.signal_family = rule.signal_family
        row.target_key = rule.target_key
        row.min_confidence = rule.min_confidence
        row.alert_level = rule.alert_level
        row.delivery_target_ids_json = None
        row.metadata_json = json.dumps({})
        row.is_deleted = False
        row.deleted_at = None
        persisted_rows.append(row)
        if row.id is not None:
            seen_ids.add(row.id)

    db.flush()
    seen_ids.update(row.id for row in persisted_rows if row.id is not None)
    for row in existing_rows:
        if row.id not in seen_ids:
            row.is_deleted = True
            row.deleted_at = datetime.utcnow()
    db.commit()
    return build_alert_rule_responses(db)


def replace_trigger_rules(db: Session, rules: list[TriggerRule]):
    ensure_alert_rule_tables()
    bundle = get_registry_bundle(db, source_rows=get_active_source_rows(db))
    plugin_component_lookup = _build_plugin_component_lookup_from_bundle(bundle)
    existing_rows = (
        db.query(SQLModels.TriggerRule)
        .filter_by(is_deleted=False)
        .order_by(SQLModels.TriggerRule.id.asc())
        .all()
    )
    existing_by_id = {row.id: row for row in existing_rows}
    source_rows = get_active_source_rows(db)
    source_by_id = {row.id: row for row in source_rows}
    option_lookup = build_alert_rule_option_lookup(
        build_alert_rule_options_response(db).model_dump()
    )

    for rule in rules:
        if rule.trigger_key not in plugin_component_lookup.get(COMPONENT_TYPE_TRIGGER, {}):
            raise HTTPException(
                status_code=400,
                detail=f"trigger plugin component {rule.trigger_key} is unavailable",
            )
        if rule.trigger_key != TRIGGER_KEY_ALERT_RULE:
            continue
        if not rule.source_ids:
            raise HTTPException(status_code=400, detail="source_ids is required for alert rules")
        for source_id in rule.source_ids:
            if source_id not in source_by_id:
                raise HTTPException(status_code=404, detail=f"source {source_id} not found")
            signal_options = option_lookup.get(source_id, {}).get(rule.signal_family or "")
            if signal_options is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"signal family {rule.signal_family} is unavailable for source {source_id}",
                )
            if signal_options.get("unavailable_reason"):
                raise HTTPException(status_code=400, detail=signal_options["unavailable_reason"])
            valid_targets = {
                str(option.get("key")).strip().lower()
                for option in signal_options.get("options", [])
            }
            if str(rule.target_key or "").strip().lower() not in valid_targets:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"invalid target '{rule.target_key}' for source {source_id} "
                        f"and signal family {rule.signal_family}"
                    ),
                )

    seen_ids = {rule.id for rule in rules if rule.id is not None}
    grouped_sort_orders: dict[tuple[str, str], int] = {}
    for rule in rules:
        row = existing_by_id.get(rule.id) if rule.id is not None else None
        if row is None:
            row = SQLModels.TriggerRule()
            db.add(row)
        key = (rule.trigger_key, rule.rule_kind)
        order = grouped_sort_orders.get(key, 0)
        grouped_sort_orders[key] = order + 1
        row.trigger_key = rule.trigger_key
        source_ids = list(rule.source_ids)
        row.source_template_id = source_ids[0] if source_ids else None
        row.source_ids_json = json.dumps(source_ids)
        row.enabled = rule.enabled
        row.sort_order = order
        row.rule_label = rule.rule_label
        row.rule_kind = rule.rule_kind
        row.signal_family = rule.signal_family
        row.anomaly_target_kind = rule.anomaly_target_kind
        row.target_key = rule.target_key
        row.min_confidence = rule.min_confidence
        row.anomaly_cutoff = rule.anomaly_cutoff
        row.alert_level = rule.alert_level
        row.delivery_target_ids_json = json.dumps(list(rule.delivery_target_ids))
        row.metadata_json = json.dumps(
            {
                **dict(rule.metadata or {}),
                "source_ids": source_ids,
                "rule_kind": rule.rule_kind,
                "anomaly_target_kind": rule.anomaly_target_kind,
                "anomaly_cutoff": rule.anomaly_cutoff,
            }
        )
        row.is_deleted = False
        row.deleted_at = None

    for row in existing_rows:
        if row.id not in seen_ids:
            row.is_deleted = True
            row.deleted_at = datetime.utcnow()
    db.commit()
    return build_trigger_rule_responses(db)


def get_connector_endpoint_rows(db: Session, connector_key: str | None = None):
    return list_connector_endpoint_rows(db, connector_key=connector_key, enabled_only=False)


def build_connector_endpoint_responses(db: Session):
    bundle = get_registry_bundle(db, source_rows=get_active_source_rows(db))
    plugin_component_lookup = _build_plugin_component_lookup_from_bundle(bundle)
    connector_components = plugin_component_lookup.get(COMPONENT_TYPE_CONNECTOR, {})
    return [
        ConnectorEndpoint(
            id=row.id,
            connector_key=row.connector_key,
            label=row.label,
            enabled=row.enabled,
            config=redact_connector_endpoint_config(get_connector_endpoint_config(row)),
            delivery_capabilities=get_connector_delivery_capabilities(row),
            resolved=row.connector_key in connector_components,
            unavailable_reason=(
                None
                if row.connector_key in connector_components
                else f"connector plugin component {row.connector_key} is unavailable"
            ),
            created_at=row.created_at.isoformat() if row.created_at is not None else None,
            updated_at=row.updated_at.isoformat() if row.updated_at is not None else None,
        )
        for row in get_connector_endpoint_rows(db)
    ]


def replace_connector_endpoints(db: Session, endpoints: list[ConnectorEndpoint]):
    ensure_connector_endpoint_tables()
    bundle = get_registry_bundle(db, source_rows=get_active_source_rows(db))
    plugin_component_lookup = _build_plugin_component_lookup_from_bundle(bundle)
    existing_rows = get_connector_endpoint_rows(db)
    existing_by_id = {row.id: row for row in existing_rows}
    seen_ids = set()
    persisted_rows = []
    for endpoint in endpoints:
        if endpoint.connector_key not in plugin_component_lookup.get(COMPONENT_TYPE_CONNECTOR, {}):
            raise HTTPException(
                status_code=400,
                detail=f"connector plugin component {endpoint.connector_key} is unavailable",
            )
        row = existing_by_id.get(endpoint.id) if endpoint.id is not None else None
        if row is None:
            row = SQLModels.ConnectorEndpoint()
            db.add(row)
        existing_config = get_connector_endpoint_config(row)
        merged_config = merge_connector_endpoint_secret_config(
            existing_config,
            dict(endpoint.config or {}),
        )
        if endpoint.connector_key == CONNECTOR_KEY_CLAUDE_API:
            try:
                validate_claude_api_config(merged_config)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        set_connector_endpoint_payload(
            row,
            connector_key=endpoint.connector_key,
            label=endpoint.label,
            enabled=endpoint.enabled,
            config=merged_config,
            delivery_capabilities=list(endpoint.delivery_capabilities),
        )
        persisted_rows.append(row)
        if row.id is not None:
            seen_ids.add(row.id)
    db.flush()
    seen_ids.update(row.id for row in persisted_rows if row.id is not None)
    for row in existing_rows:
        if row.id not in seen_ids:
            row.is_deleted = True
            row.deleted_at = datetime.utcnow()
    db.commit()
    return build_connector_endpoint_responses(db)


def get_telegram_trigger_subscription_rows(db: Session):
    ensure_telegram_subscription_tables()
    return get_connector_endpoint_rows(db, CONNECTOR_KEY_TELEGRAM)


def build_telegram_trigger_subscription_responses(db: Session):
    return [
        TelegramTriggerSubscription(
            id=row.id,
            enabled=row.enabled,
            subscription_label=row.label,
            bot_token=(
                MASKED_SECRET_VALUE
                if str(get_connector_endpoint_config(row).get("bot_token", "") or "").strip()
                else ""
            ),
            chat_id=str(get_connector_endpoint_config(row).get("chat_id", "") or ""),
            send_media=bool(get_connector_endpoint_config(row).get("send_media", False)),
            media_source=str(get_connector_endpoint_config(row).get("media_source", "none") or "none"),
            created_at=row.created_at.isoformat() if row.created_at is not None else None,
            updated_at=row.updated_at.isoformat() if row.updated_at is not None else None,
        )
        for row in get_telegram_trigger_subscription_rows(db)
    ]


def replace_telegram_trigger_subscriptions(
    db: Session,
    subscriptions: list[TelegramTriggerSubscription],
):
    ensure_telegram_subscription_tables()
    existing_rows = get_telegram_trigger_subscription_rows(db)
    existing_by_id = {row.id: row for row in existing_rows}

    seen_ids = set()
    persisted_rows = []
    for subscription in subscriptions:
        row = (
            existing_by_id.get(subscription.id)
            if subscription.id is not None
            else None
        )
        if row is None:
            row = SQLModels.ConnectorEndpoint()
            db.add(row)
        existing_config = get_connector_endpoint_config(row)
        set_connector_endpoint_payload(
            row,
            connector_key=CONNECTOR_KEY_TELEGRAM,
            label=subscription.subscription_label,
            enabled=subscription.enabled,
            config=merge_connector_endpoint_secret_config(
                existing_config,
                {
                    "bot_token": subscription.bot_token,
                    "chat_id": subscription.chat_id,
                    "send_media": bool(subscription.send_media),
                    "media_source": str(subscription.media_source or "none"),
                },
            ),
            delivery_capabilities=["text", "photo"],
        )
        persisted_rows.append(row)
        if row.id is not None:
            seen_ids.add(row.id)

    db.flush()
    seen_ids.update(row.id for row in persisted_rows if row.id is not None)
    for row in existing_rows:
        if row.id not in seen_ids:
            row.is_deleted = True
            row.deleted_at = datetime.utcnow()
    db.commit()
    return build_telegram_trigger_subscription_responses(db)


def get_apple_message_trigger_subscription_rows(db: Session):
    ensure_apple_message_subscription_tables()
    return get_connector_endpoint_rows(db, CONNECTOR_KEY_APPLE_MESSAGES)


def build_apple_message_trigger_subscription_responses(db: Session):
    return [
        AppleMessageTriggerSubscription(
            id=row.id,
            enabled=row.enabled,
            subscription_label=row.label,
            recipient_handle=str(get_connector_endpoint_config(row).get("recipient_handle", "") or ""),
            service=str(get_connector_endpoint_config(row).get("service", "iMessage") or "iMessage"),
            created_at=row.created_at.isoformat() if row.created_at is not None else None,
            updated_at=row.updated_at.isoformat() if row.updated_at is not None else None,
        )
        for row in get_apple_message_trigger_subscription_rows(db)
    ]


def replace_apple_message_trigger_subscriptions(
    db: Session,
    subscriptions: list[AppleMessageTriggerSubscription],
):
    ensure_apple_message_subscription_tables()
    existing_rows = get_apple_message_trigger_subscription_rows(db)
    existing_by_id = {row.id: row for row in existing_rows}

    seen_ids = set()
    persisted_rows = []
    for subscription in subscriptions:
        row = (
            existing_by_id.get(subscription.id)
            if subscription.id is not None
            else None
        )
        if row is None:
            row = SQLModels.ConnectorEndpoint()
            db.add(row)
        set_connector_endpoint_payload(
            row,
            connector_key=CONNECTOR_KEY_APPLE_MESSAGES,
            label=subscription.subscription_label,
            enabled=subscription.enabled,
            config={
                "recipient_handle": subscription.recipient_handle,
                "service": subscription.service,
            },
            delivery_capabilities=["text"],
        )
        persisted_rows.append(row)
        if row.id is not None:
            seen_ids.add(row.id)

    db.flush()
    seen_ids.update(row.id for row in persisted_rows if row.id is not None)
    for row in existing_rows:
        if row.id not in seen_ids:
            row.is_deleted = True
            row.deleted_at = datetime.utcnow()
    db.commit()
    return build_apple_message_trigger_subscription_responses(db)


def get_claude_api_connector_rows(db: Session):
    ensure_claude_api_connector_tables()
    return get_connector_endpoint_rows(db, CONNECTOR_KEY_CLAUDE_API)


def build_claude_api_connector_responses(db: Session):
    return [
        ClaudeApiConnectorEndpoint(
            id=row.id,
            enabled=row.enabled,
            connector_label=row.label,
            base_url=str(get_connector_endpoint_config(row).get("base_url", "") or ""),
            auth_token=(
                MASKED_SECRET_VALUE
                if str(get_connector_endpoint_config(row).get("auth_token", "") or "").strip()
                else ""
            ),
            timeout_seconds=int(get_connector_endpoint_config(row).get("timeout_seconds", 10) or 10),
            retry_count=int(get_connector_endpoint_config(row).get("retry_count", 1) or 1),
            created_at=row.created_at.isoformat() if row.created_at is not None else None,
            updated_at=row.updated_at.isoformat() if row.updated_at is not None else None,
        )
        for row in get_claude_api_connector_rows(db)
    ]


def replace_claude_api_connectors(
    db: Session,
    endpoints: list[ClaudeApiConnectorEndpoint],
):
    ensure_claude_api_connector_tables()
    existing_rows = get_claude_api_connector_rows(db)
    existing_by_id = {row.id: row for row in existing_rows}

    seen_ids = set()
    persisted_rows = []
    for endpoint in endpoints:
        row = existing_by_id.get(endpoint.id) if endpoint.id is not None else None
        if row is None:
            row = SQLModels.ConnectorEndpoint()
            db.add(row)
        existing_config = get_connector_endpoint_config(row)
        config = merge_connector_endpoint_secret_config(
            existing_config,
            {
                "base_url": endpoint.base_url,
                "auth_token": endpoint.auth_token,
                "timeout_seconds": endpoint.timeout_seconds,
                "retry_count": endpoint.retry_count,
            },
        )
        try:
            validate_claude_api_config(config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        set_connector_endpoint_payload(
            row,
            connector_key=CONNECTOR_KEY_CLAUDE_API,
            label=endpoint.connector_label,
            enabled=endpoint.enabled,
            config=config,
            delivery_capabilities=["json", "sync", "retry"],
        )
        persisted_rows.append(row)
        if row.id is not None:
            seen_ids.add(row.id)

    db.flush()
    seen_ids.update(row.id for row in persisted_rows if row.id is not None)
    for row in existing_rows:
        if row.id not in seen_ids:
            row.is_deleted = True
            row.deleted_at = datetime.utcnow()
    db.commit()
    return build_claude_api_connector_responses(db)


async def store_uploaded_source_video(
    file: UploadFile,
    db: Session,
):
    validation_error = validate_uploaded_video_file(file.filename, file.content_type)
    if validation_error is not None:
        raise HTTPException(status_code=400, detail=validation_error)

    upload_dir = get_upload_dir()
    stored_path = upload_dir / build_upload_filename(file.filename)
    size_bytes = 0
    try:
        with stored_path.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "uploaded file is too large; "
                            f"supported video types: {format_supported_video_extensions()}"
                        ),
                    )
                handle.write(chunk)
    except Exception:
        if stored_path.exists():
            stored_path.unlink()
        raise
    finally:
        await file.close()

    checksum = compute_sha256(stored_path)
    upload_row = SQLModels.UploadedMedia(
        original_filename=file.filename,
        stored_path=str(stored_path),
        checksum_sha256=checksum,
        size_bytes=size_bytes,
        lifecycle_state="staged",
    )
    db.add(upload_row)
    db.commit()
    db.refresh(upload_row)
    return UploadResponse(upload=db_upload_to_api(upload_row))


def delete_uploaded_source_record(upload_id: int, db: Session):
    upload_row = (
        db.query(SQLModels.UploadedMedia)
        .filter_by(id=upload_id, is_deleted=False)
        .first()
    )
    if upload_row is None:
        raise HTTPException(status_code=404, detail="upload not found")
    source_reference = (
        db.query(SQLModels.InputSourceTemplate)
        .filter_by(upload_id=upload_id, is_deleted=False)
        .first()
    )
    if source_reference is not None:
        raise HTTPException(status_code=409, detail="upload is still referenced by a source")
    stored_path = Path(upload_row.stored_path)
    if stored_path.exists():
        stored_path.unlink()
    upload_row.lifecycle_state = "deleted"
    upload_row.is_deleted = True
    upload_row.deleted_at = datetime.utcnow()
    db.commit()
    return {"status": "deleted", "upload_id": upload_id}


def build_runtime_cfg(db: Session, run_identifier: str):
    source_rows = [row for row in get_active_source_rows(db) if row.enabled]
    if not source_rows:
        raise HTTPException(status_code=400, detail="at least one enabled source is required")

    registry_bundle = get_registry_bundle(db, source_rows=source_rows)
    has_gpu = bool(collect_resource_snapshot({}).get("gpus"))
    defaults = build_default_bindings(registry_bundle, has_gpu=has_gpu)
    upload_rows = get_upload_rows_by_id(
        db, [row.upload_id for row in source_rows if row.upload_id is not None]
    )
    upload_paths = {}
    source_errors = []
    for source_row in source_rows:
        upload_row = upload_rows.get(source_row.upload_id)
        upload_path = upload_row.stored_path if upload_row is not None else None
        derived_error = derive_source_error(
            kind=source_row.kind,
            enabled=source_row.enabled,
            upload_id=source_row.upload_id,
            upload_path=upload_path,
            upload_exists=Path(upload_path).exists() if upload_path else False,
            upload_lifecycle_state=(
                upload_row.lifecycle_state if upload_row is not None else None
            ),
        )
        if derived_error is None:
            if is_hybrid_local_cpu_runtime():
                derived_error = probe_source_via_local_worker(
                    source_row.kind,
                    source_row.source_value,
                    upload_path=upload_path,
                )
            else:
                derived_error = probe_source_connection(
                    source_row.kind,
                    source_row.source_value,
                    upload_path=upload_path,
                    timeout_ms=SOURCE_PROBE_TIMEOUT_MS,
                )
        source_row.last_error = derived_error
        if derived_error:
            source_errors.append(f"{source_row.label}: {derived_error}")
            continue
        if source_row.upload_id is not None and upload_path is not None:
            upload_paths[source_row.upload_id] = (
                build_host_upload_path(upload_path)
                if is_hybrid_local_cpu_runtime()
                else upload_path
            )
    model_health = build_model_health(registry_bundle, has_gpu=has_gpu)
    source_errors.extend(
        build_enabled_source_binding_errors(
            registry_bundle,
            source_rows,
            model_health,
            has_gpu=has_gpu,
        )
    )
    if source_errors:
        db.commit()
        raise HTTPException(status_code=409, detail="; ".join(source_errors))

    runtime_cfg = clone_cfg()
    runtime_cfg.run_id = run_identifier
    runtime_cfg.input.cameras = build_runtime_camera_map(source_rows, upload_paths)
    if is_hybrid_local_cpu_runtime():
        # Local hybrid workers run headless; disable GUI preview paths and persist
        # periodic frames so status APIs can surface concrete frame progress.
        runtime_cfg.output.visualize.show_vid = False
        runtime_cfg.output.frames.save_frames = True
        runtime_cfg.output.frames.save_interval = 1
    runtime_cfg.model_bindings = build_runtime_binding_block(
        source_rows,
        registry_bundle,
        defaults=defaults,
    )
    runtime_cfg.model_registry = registry_bundle.get("models", {})
    runtime_cfg.anomaly_stage_1_models = registry_bundle.get("models", {}).get("anomaly_stage_1", {})
    runtime_cfg.anomaly_stage_2_models = registry_bundle.get("models", {}).get("anomaly_stage_2", {})
    return runtime_cfg, source_rows


def publish_system_message(message: DataModels.SystemMessage):
    get_system_publisher().publish_message(message)


def normalize_module_name(module_name: str) -> str:
    normalized = module_name.strip().upper()
    valid = {
        ModuleNames.INGESTOR,
        ModuleNames.ANOMALY,
    }
    if normalized not in valid:
        raise HTTPException(status_code=400, detail="invalid module name")
    return normalized


def process_messages():
    global status
    global module_status
    global module_metrics
    global module_runtime_details
    global frame_id
    global total_frames

    consumer = get_status_consumer()
    while True:
        try:
            message = consumer.queue.get(timeout=SHORT_SLEEP)
        except queue.Empty:
            break
        extra = message.extra
        if extra is not None:
            if message.status in (DataModels.Status.INFO, DataModels.Status.STOPPED):
                if "frame_id" in extra:
                    frame_id = extra.get("frame_id")
                if "total_frames" in extra:
                    total_frames = extra.get("total_frames")
            if message.status == DataModels.Status.INFO:
                if message.module:
                    backpressure = extra.get("backpressure")
                    queue_depths = extra.get("queue_depths")
                    if backpressure is not None:
                        module_metrics[message.module] = dict(backpressure)
                    elif queue_depths is not None:
                        module_metrics[message.module] = summarize_queue_backpressure(
                            queue_depths
                        )
                    module_runtime_details.setdefault(message.module, {}).update(
                        dict(extra)
                    )
        if message.module in module_status:
            module_status[message.module] = message.status
        else:
            logger.warning("Received status update for unknown module %s", message.module)


def refresh_runtime_status():
    global status

    process_messages()
    relevant_statuses = [
        normalize_module_status(module_status.get(module_name, DataModels.Status.IDLE))
        for module_name in get_expected_module_names()
    ]
    next_status, reset_frames = derive_system_status(status, relevant_statuses)
    with state_lock:
        status = next_status
        if reset_frames:
            reset_runtime_state(clear_run=True)
    return status


def process_images(base64_images, save_dir=""):
    if not base64_images:
        raise HTTPException(status_code=400, detail="no images provided")
    images = []
    for image in base64_images:
        try:
            decoded = decode_base64(image)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if decoded.size == 0:
            raise HTTPException(status_code=400, detail="decoded image is empty")
        images.append(decoded)
    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        for index, image in enumerate(images):
            success = cv2.imwrite(os.path.join(save_dir, f"{index}.jpg"), image)
            if not success:
                raise HTTPException(status_code=500, detail="failed to write poi crop")
    features = get_feature_extractor()(images)
    if len(features) == 0:
        raise HTTPException(status_code=400, detail="no features extracted from images")
    return np.mean(features, axis=0)


def get_run_row(db: Session, run_identifier: str | None = None):
    if run_identifier:
        run_row = db.query(SQLModels.Run).filter_by(run_identifier=run_identifier).first()
        if run_row is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run_row
    return db.query(SQLModels.Run).order_by(SQLModels.Run.created_at.desc()).first()


def build_feed_location(camera_id: int | None = None, zone_id: int | None = None):
    return FeedLocation(camera_id=camera_id, zone_id=zone_id)


def build_run_summary(db: Session, run_row: SQLModels.Run):
    recordings = (
        db.query(SQLModels.CameraRecording)
        .filter_by(run_id=run_row.id, is_deleted=False)
        .all()
    )
    return RunSummary(
        run_identifier=run_row.run_identifier,
        start_time=(
            run_row.start_datetime.isoformat() if run_row.start_datetime is not None else None
        ),
        status=infer_run_status(
            run_row.run_identifier,
            current_run_id=run_id,
            system_status=status,
        ),
        incident_count=db.query(SQLModels.Incident).filter_by(run_id=run_row.id).count(),
        entity_count=db.query(SQLModels.Person).filter_by(run_id=run_row.id, is_deleted=False).count()
        + db.query(SQLModels.Bag).filter_by(run_id=run_row.id, is_deleted=False).count(),
        source_count=len(recordings),
        camera_count=len({recording.cam_id for recording in recordings if recording.cam_id is not None}),
    )


def build_run_summaries(db: Session, limit: int | None = None):
    normalized_limit = normalize_feed_limit(limit, default=10, max_limit=50)
    run_rows = (
        db.query(SQLModels.Run)
        .order_by(SQLModels.Run.created_at.desc())
        .limit(normalized_limit)
        .all()
    )
    return [build_run_summary(db, run_row) for run_row in run_rows]


def get_alert_incident_lookup(db: Session, incident_ids: list[int]) -> dict[int, SQLModels.AlertIncident]:
    if not incident_ids:
        return {}
    ensure_alert_rule_tables()
    rows = (
        db.query(SQLModels.AlertIncident)
        .filter(
            SQLModels.AlertIncident.incident_id.in_(incident_ids),
            SQLModels.AlertIncident.is_deleted.is_(False),
        )
        .all()
    )
    return {row.incident_id: row for row in rows}


def build_incident_feed_items(
    db: Session,
    run_row: SQLModels.Run | None,
    *,
    limit: int | None = None,
):
    if run_row is None:
        return []
    normalized_limit = normalize_feed_limit(limit)
    incident_rows = (
        db.query(SQLModels.Incident)
        .filter_by(run_id=run_row.id)
        .order_by(SQLModels.Incident.created_at.desc())
        .limit(normalized_limit)
        .all()
    )
    alert_lookup = get_alert_incident_lookup(
        db,
        [incident_row.id for incident_row in incident_rows],
    )
    return [
        AlgorithmIncidentFeedItem(
            run_identifier=run_row.run_identifier,
            incident_id=create_incident_id(incident_row),
            incident_type=incident_row.incident_type,
            display_title=(
                alert_lookup[incident_row.id].title
                if incident_row.id in alert_lookup
                else None
            ),
            alert_level=(
                alert_lookup[incident_row.id].alert_level
                if incident_row.id in alert_lookup
                else None
            ),
            metadata=(
                {
                    "signal_family": alert_lookup[incident_row.id].signal_family,
                    "matched_target": alert_lookup[incident_row.id].matched_target,
                    "confidence": float(alert_lookup[incident_row.id].confidence),
                }
                if incident_row.id in alert_lookup
                else {}
            ),
            status=incident_row.status,
            incident_time=(
                incident_row.created_at.isoformat()
                if incident_row.created_at is not None
                else None
            ),
            last_update_time=(
                incident_row.updated_at.isoformat()
                if incident_row.updated_at is not None
                else None
            ),
            last_updated_by=incident_row.updated_by,
            location=build_feed_location(
                camera_id=incident_row.camera_id,
                zone_id=incident_row.zone_id,
            ),
        )
        for incident_row in incident_rows
    ]


def build_entity_incident_lookup(db: Session, run_row: SQLModels.Run):
    incident_rows = db.query(SQLModels.Incident).filter_by(run_id=run_row.id).all()
    incident_ids = {incident_row.id: create_incident_id(incident_row) for incident_row in incident_rows}
    person_lookup = {}
    bag_lookup = {}
    for mapping in db.query(SQLModels.IncidentPersonMapping).filter(
        SQLModels.IncidentPersonMapping.incident_id.in_(incident_ids.keys())
    ):
        person_lookup.setdefault(mapping.person_id, []).append(
            incident_ids[mapping.incident_id]
        )
    for mapping in db.query(SQLModels.IncidentBagMapping).filter(
        SQLModels.IncidentBagMapping.incident_id.in_(incident_ids.keys())
    ):
        bag_lookup.setdefault(mapping.bag_id, []).append(incident_ids[mapping.incident_id])
    return person_lookup, bag_lookup


def build_entity_feed_items(
    db: Session,
    run_row: SQLModels.Run | None,
    *,
    limit: int | None = None,
):
    if run_row is None:
        return []

    normalized_limit = normalize_feed_limit(limit)
    person_rows = db.query(SQLModels.Person).filter_by(run_id=run_row.id, is_deleted=False).all()
    bag_rows = db.query(SQLModels.Bag).filter_by(run_id=run_row.id, is_deleted=False).all()
    person_incidents, bag_incidents = build_entity_incident_lookup(db, run_row)

    combined_rows = [
        ("person", row.created_at or datetime.min, row)
        for row in person_rows
    ] + [
        ("bag", row.created_at or datetime.min, row)
        for row in bag_rows
    ]
    combined_rows.sort(key=lambda item: item[1], reverse=True)

    entities = []
    for entity_kind, _, entity_row in combined_rows[:normalized_limit]:
        if entity_kind == "person":
            entity_type = EntityType.PERSON
            last_node = get_last_journey_node(entity_row.id, EntityType.PERSON, db)
            associated_incident_ids = sorted(set(person_incidents.get(entity_row.id, [])))
        else:
            entity_type = EntityType.BAG
            last_node = get_last_journey_node(entity_row.id, EntityType.BAG, db)
            associated_incident_ids = sorted(set(bag_incidents.get(entity_row.id, [])))

        if last_node is None:
            entity_id = (
                f"{entity_type}-{entity_row.created_at.strftime('%Y%m%d')}-{entity_row.id}"
                if entity_row.created_at is not None
                else f"{entity_type}-{entity_row.id}"
            )
            last_seen_time = (
                entity_row.created_at.isoformat()
                if entity_row.created_at is not None
                else None
            )
            location = None
        else:
            entity_id = create_entity_id(last_node, entity_type, entity_row.id)
            last_seen_time = (
                datetime.fromtimestamp(last_node.stop_timestamp).isoformat()
                if last_node.stop_timestamp
                else datetime.now().isoformat()
            )
            location = build_feed_location(
                camera_id=last_node.camera_id,
                zone_id=last_node.zone_id,
            )

        entities.append(
            AlgorithmEntityFeedItem(
                run_identifier=run_row.run_identifier,
                entity_id=entity_id,
                entity_type=EntityType.FULL[entity_type],
                last_seen_time=last_seen_time,
                location=location,
                associated_incident_ids=associated_incident_ids,
            )
        )
    return entities


def build_resource_event_records(db: Session, limit: int | None = None):
    normalized_limit = normalize_feed_limit(limit, default=15, max_limit=100)
    event_rows = (
        db.query(SQLModels.ResourceEvent)
        .order_by(SQLModels.ResourceEvent.created_at.desc())
        .limit(normalized_limit)
        .all()
    )
    return [
        ResourceEventRecord(
            created_at=event_row.created_at.isoformat(),
            event_type=event_row.event_type,
            severity=event_row.severity,
            message=event_row.message,
            metadata=parse_serialized_json(event_row.metadata_json),
        )
        for event_row in event_rows
    ]


def build_anomaly_feed_items(
    db: Session,
    run_row: SQLModels.Run | None,
    *,
    limit: int | None = None,
):
    if run_row is None:
        return []
    normalized_limit = normalize_feed_limit(limit)
    anomaly_rows = (
        db.query(SQLModels.AnomalyEvent)
        .filter_by(run_id=run_row.id, is_deleted=False)
        .order_by(SQLModels.AnomalyEvent.created_at.desc())
        .limit(normalized_limit)
        .all()
    )
    def parse_list(value):
        parsed = parse_serialized_json(value)
        return parsed if isinstance(parsed, list) else []

    def build_anomaly_title(row, visible_items, visible_activities):
        if row.title:
            return row.title
        parts = []
        if visible_items:
            parts.append(", ".join(str(item) for item in visible_items if item))
        if visible_activities:
            parts.append(", ".join(str(item) for item in visible_activities if item))
        if parts:
            return f"Anomaly found: {'; '.join(parts)}"
        return row.category

    return [
        (
            lambda visible_items, visible_activities: APIAnomalyEvent(
                event_id=anomaly_row.event_key,
                run_id=run_row.run_identifier,
                source_id=anomaly_row.source_template_id,
                camera_id=anomaly_row.camera_id,
                frame_id=anomaly_row.frame_id,
                event_time=anomaly_row.created_at.isoformat()
                if anomaly_row.created_at is not None
                else None,
                title=build_anomaly_title(
                    anomaly_row,
                    visible_items,
                    visible_activities,
                ),
                model_key=anomaly_row.model_key,
                stage_1_model_key=anomaly_row.stage_1_model_key,
                stage_2_model_key=anomaly_row.stage_2_model_key,
                category=anomaly_row.category,
                score=anomaly_row.score,
                reasoning=anomaly_row.reasoning,
                visible_items=visible_items,
                visible_activities=visible_activities,
                asset_references=[
                    APIAssetReference.model_validate(asset)
                    for asset in (parse_serialized_json(anomaly_row.asset_refs_json) or [])
                ],
            )
        )(
            parse_list(anomaly_row.visible_items_json),
            parse_list(anomaly_row.visible_activities_json),
        )
        for anomaly_row in anomaly_rows
    ]


def build_model_result_log_page(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    stage: str | None = None,
    source_id: int | None = None,
    result_query: str | None = None,
    run_identifier: str | None = None,
):
    normalized_page = max(1, int(page or 1))
    normalized_page_size = min(100, max(1, int(page_size or 20)))
    query = db.query(SQLModels.ModelResultLog).filter_by(is_deleted=False)
    if run_identifier:
        run_row = (
            db.query(SQLModels.Run)
            .filter_by(run_identifier=run_identifier, is_deleted=False)
            .order_by(SQLModels.Run.id.desc())
            .first()
        )
        if run_row is None:
            return ModelResultLogPage(
                page=normalized_page,
                page_size=normalized_page_size,
                total=0,
                has_more=False,
                rate_summary={},
                records=[],
            )
        query = query.filter_by(run_id=run_row.id)
    if stage:
        query = query.filter_by(stage=stage)
    if source_id is not None:
        query = query.filter_by(source_template_id=source_id)
    if result_query:
        like_value = f"%{result_query.strip()}%"
        query = query.filter(
            SQLModels.ModelResultLog.result_summary.ilike(like_value)
            | SQLModels.ModelResultLog.source_label.ilike(like_value)
            | SQLModels.ModelResultLog.model_display_name.ilike(like_value)
            | SQLModels.ModelResultLog.model_key.ilike(like_value)
        )
    total = query.count()
    rows = (
        query.order_by(
            SQLModels.ModelResultLog.created_at.desc(),
            SQLModels.ModelResultLog.id.desc(),
        )
        .offset((normalized_page - 1) * normalized_page_size)
        .limit(normalized_page_size)
        .all()
    )
    run_ids = {row.run_id for row in rows}
    runs_by_id = {
        run_row.id: run_row.run_identifier
        for run_row in db.query(SQLModels.Run)
        .filter(SQLModels.Run.id.in_(run_ids))
        .all()
    } if run_ids else {}
    records = [
        {
            "id": row.id,
            "created_at": row.created_at.isoformat() if row.created_at is not None else None,
            "run_id": runs_by_id.get(row.run_id),
            "source_id": row.source_template_id,
            "source_label": row.source_label,
            "camera_id": row.camera_id,
            "stage": row.stage,
            "model_key": row.model_key,
            "model_display_name": row.model_display_name,
            "frame_id": row.frame_id,
            "result_summary": row.result_summary,
            "result_payload": parse_serialized_json(row.result_payload_json) or {},
        }
        for row in rows
    ]
    recent_cutoff = datetime.utcnow().timestamp() - 60.0
    recent_counts: dict[str, int] = {}
    recent_rows = (
        query.order_by(
            SQLModels.ModelResultLog.created_at.desc(),
            SQLModels.ModelResultLog.id.desc(),
        )
        .limit(500)
        .all()
    )
    for row in recent_rows:
        if row.created_at is None or row.created_at.timestamp() < recent_cutoff:
            continue
        stage_key = str(row.stage or "unknown")
        recent_counts[stage_key] = recent_counts.get(stage_key, 0) + 1
    return ModelResultLogPage(
        page=normalized_page,
        page_size=normalized_page_size,
        total=total,
        has_more=normalized_page * normalized_page_size < total,
        rate_summary={
            stage_key: round(count / 60.0, 2)
            for stage_key, count in recent_counts.items()
        },
        records=records,
    )


def build_algorithm_feed_payload(
    db: Session,
    *,
    run_identifier: str | None = None,
    limit: int | None = None,
):
    current_status = refresh_runtime_status()
    selected_run = get_run_row(db, run_identifier)
    snapshot = get_current_resource_snapshot(db)
    source_rows = get_active_source_rows(db)
    registry_bundle = get_registry_bundle(db, source_rows=source_rows)
    return AlgorithmFeed(
        generated_at=utc_now_iso(),
        run_identifier=selected_run.run_identifier if selected_run is not None else None,
        current_run_id=run_id,
        system_status=current_status,
        resources=ResourceSnapshot.model_validate(snapshot),
        admission=AdmissionStatus.model_validate(snapshot["admission"]),
        sources=build_source_responses(db, snapshot),
        model_bindings=build_model_binding_responses(
            registry_bundle,
            source_rows,
            has_gpu=bool(snapshot.get("gpus")),
        ),
        incidents=build_incident_feed_items(db, selected_run, limit=limit),
        entities=build_entity_feed_items(db, selected_run, limit=limit),
        anomalies=build_anomaly_feed_items(db, selected_run, limit=limit),
    )


@external_router.post("/start")
async def start(db: Session = Depends(get_db)):
    global status
    global run_id

    current_status = refresh_runtime_status()
    with state_lock:
        if current_status in {SystemStatus.INITIALIZING, SystemStatus.RUNNING}:
            raise HTTPException(
                status_code=409, detail="system is already starting or running"
            )
    snapshot = get_current_resource_snapshot(db)
    admission = snapshot.get("admission") or {"allowed": True, "reason": None}
    if not admission.get("allowed", True):
        reason = admission.get("reason") or "start rejected by admission control"
        log_resource_event(
            PersistedEvent(
                event_type="start_denied",
                severity="warning",
                message=reason,
                metadata={"run_id": run_id, "admission": admission},
            )
        )
        raise HTTPException(status_code=409, detail=reason)
    if is_hybrid_local_cpu_runtime():
        require_local_worker_ready()

    next_run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    runtime_cfg, source_rows = build_runtime_cfg(db, next_run_id)
    active_upload_ids = {
        row.upload_id for row in source_rows if row.upload_id is not None
    }
    sync_upload_lifecycle_states(
        db,
        source_rows=source_rows,
        active_upload_ids=active_upload_ids,
    )
    db.commit()

    with state_lock:
        reset_runtime_state(clear_run=False)
        run_id = next_run_id
        status = SystemStatus.INITIALIZING

    try:
        publish_system_message(
            DataModels.SystemMessage(
                command=DataModels.SystemCommand.START,
                config=runtime_cfg,
            )
        )
        log_resource_event(
            PersistedEvent(
                event_type="system_start",
                severity="info",
                message="system start published",
                metadata={
                    "run_id": run_id,
                    "enabled_sources": len(source_rows),
                },
            )
        )
    except Exception as exc:
        sync_upload_lifecycle_states(db, source_rows=source_rows, active_upload_ids=set())
        db.commit()
        with state_lock:
            status = SystemStatus.IDLE
            reset_runtime_state(clear_run=True)
        if isinstance(exc, HTTPException):
            raise
        logger.exception("Failed to publish start command")
        raise HTTPException(
            status_code=503, detail="failed to publish start command"
        ) from exc
    return {"status": "starting", "run_id": run_id}


@external_router.post("/stop")
async def stop(db: Session = Depends(get_db)):
    global status

    current_status = refresh_runtime_status()
    with state_lock:
        if current_status == SystemStatus.IDLE:
            return {"status": "idle"}
        status = SystemStatus.STOPPING
    try:
        publish_system_message(
            DataModels.SystemMessage(command=DataModels.SystemCommand.STOP)
        )
        sync_upload_lifecycle_states(db, active_upload_ids=set())
        db.commit()
        log_resource_event(
            PersistedEvent(
                event_type="system_stop",
                severity="info",
                message="system stop published",
                metadata={"run_id": run_id},
            )
        )
    except Exception as exc:
        with state_lock:
            status = (
                SystemStatus.ERROR
                if get_error_modules(module_status)
                else SystemStatus.RUNNING
            )
        if isinstance(exc, HTTPException):
            raise
        logger.exception("Failed to publish stop command")
        raise HTTPException(
            status_code=503, detail="failed to publish stop command"
        ) from exc
    return {"status": "stopping"}


@external_router.get("/status", response_model=Status)
def get_status(db: Session = Depends(get_db)):
    global status
    current_status = refresh_runtime_status()
    snapshot = get_current_resource_snapshot(db)
    snapshot_module_status = merge_hybrid_operator_status(
        snapshot.get("module_status"),
        snapshot.get("dependency_status"),
        get_local_worker_health() if is_hybrid_local_cpu_runtime() else None,
    )
    effective_statuses = [
        normalize_module_status(
            snapshot_module_status.get(
                module_name,
                module_status.get(module_name, DataModels.Status.IDLE),
            )
        )
        for module_name in get_expected_module_names()
    ]
    reconciled_status, _ = derive_system_status(current_status, effective_statuses)
    if reconciled_status != current_status:
        with state_lock:
            status = reconciled_status
        current_status = reconciled_status
    effective_frame_id = frame_id
    if is_hybrid_local_cpu_runtime():
        db_frame_id = get_latest_run_frame_id(db)
        if db_frame_id is not None:
            effective_frame_id = db_frame_id
    sources = build_source_responses(db, snapshot)
    return Status(
        status=current_status,
        frame_id=effective_frame_id,
        total_frames=total_frames,
        module_status=snapshot_module_status,
        error_modules=get_error_modules(snapshot_module_status),
        run_id=run_id,
        sources=sources,
        resources=ResourceSnapshot.model_validate(snapshot),
        admission=AdmissionStatus.model_validate(snapshot["admission"]),
    )


@external_router.get("/sources", response_model=list[InputSource])
def get_sources(db: Session = Depends(get_db)):
    snapshot = get_current_resource_snapshot(db)
    return build_source_responses(db, snapshot)


@external_router.put("/sources", response_model=list[InputSource])
def update_sources(sources: list[InputSource], db: Session = Depends(get_db)):
    return upsert_sources_and_build_response(db, sources)


@external_router.get("/settings/input-sources", response_model=list[InputSource])
def get_settings_input_sources(db: Session = Depends(get_db)):
    return get_sources(db)


@external_router.put("/settings/input-sources", response_model=list[InputSource])
def replace_settings_input_sources(
    sources: list[InputSource],
    db: Session = Depends(get_db),
):
    return upsert_sources_and_build_response(db, sources)


@external_router.post("/settings/input-sources", response_model=list[InputSource])
def add_settings_input_source(source: InputSource, db: Session = Depends(get_db)):
    return append_source(db, source)


@external_router.get("/settings/anomaly-prompts", response_model=AnomalyPromptSettings)
def get_anomaly_prompt_settings():
    return read_anomaly_prompt_settings()


@external_router.get("/settings/anomaly-prompts/standard", response_model=AnomalyPromptSettings)
def get_standard_anomaly_prompt_settings():
    return read_standard_anomaly_prompt_settings()


@external_router.put("/settings/anomaly-prompts", response_model=AnomalyPromptSettings)
def update_anomaly_prompt_settings(payload: AnomalyPromptSettings):
    return write_anomaly_prompt_settings(payload)


@external_router.get("/trigger-zoo", response_model=list[TriggerZooEntry])
def get_trigger_zoo(db: Session = Depends(get_db)):
    bundle = get_registry_bundle(db, source_rows=get_active_source_rows(db))
    trigger_entries = bundle.get("plugin_catalog", {}).get("triggers") or load_trigger_zoo()
    return [TriggerZooEntry.model_validate(entry) for entry in trigger_entries]


@external_router.get("/connector-zoo", response_model=list[ConnectorZooEntry])
def get_connector_zoo(db: Session = Depends(get_db)):
    bundle = get_registry_bundle(db, source_rows=get_active_source_rows(db))
    connector_entries = bundle.get("plugin_catalog", {}).get("connectors") or load_connector_zoo()
    return [ConnectorZooEntry.model_validate(entry) for entry in connector_entries]


@external_router.get("/rule-set-zoo", response_model=list[RuleSetZooEntry])
def get_rule_set_zoo(db: Session = Depends(get_db)):
    bundle = get_registry_bundle(db, source_rows=get_active_source_rows(db))
    rule_set_entries = bundle.get("plugin_catalog", {}).get("rule_sets") or load_rule_set_zoo()
    return [RuleSetZooEntry.model_validate(entry) for entry in rule_set_entries]


@external_router.get("/plugins", response_model=list[PluginBundleRecord])
def get_plugins(db: Session = Depends(get_db)):
    get_registry_bundle(db, source_rows=get_active_source_rows(db))
    return build_plugin_bundle_responses(db)


@external_router.get("/plugins/components", response_model=list[PluginComponentRecord])
def get_plugin_components(plugin_key: str | None = None, db: Session = Depends(get_db)):
    get_registry_bundle(db, source_rows=get_active_source_rows(db))
    return build_plugin_component_responses(db, plugin_key=plugin_key)


@external_router.get("/plugins/{plugin_key}", response_model=PluginBundleRecord)
def get_plugin(plugin_key: str, db: Session = Depends(get_db)):
    get_registry_bundle(db, source_rows=get_active_source_rows(db))
    for plugin in build_plugin_bundle_responses(db):
        if plugin.plugin_key == plugin_key:
            return plugin
    raise HTTPException(status_code=404, detail="plugin not found")


@external_router.get("/settings/trigger-rules", response_model=list[TriggerRule])
def get_settings_trigger_rules(db: Session = Depends(get_db)):
    return build_trigger_rule_responses(db)


@external_router.get("/settings/appearance", response_model=AppearanceSettings)
def get_settings_appearance(db: Session = Depends(get_db)):
    return read_appearance_settings(db)


@external_router.put("/settings/appearance", response_model=AppearanceSettings)
def update_settings_appearance(
    payload: AppearanceSettings,
    db: Session = Depends(get_db),
):
    return write_appearance_settings(db, payload)


@external_router.put("/settings/trigger-rules", response_model=list[TriggerRule])
def update_settings_trigger_rules(
    rules: list[TriggerRule],
    db: Session = Depends(get_db),
):
    return replace_trigger_rules(db, rules)


@external_router.get("/settings/connector-endpoints", response_model=list[ConnectorEndpoint])
def get_settings_connector_endpoints(db: Session = Depends(get_db)):
    return build_connector_endpoint_responses(db)


@external_router.put("/settings/connector-endpoints", response_model=list[ConnectorEndpoint])
def update_settings_connector_endpoints(
    endpoints: list[ConnectorEndpoint],
    db: Session = Depends(get_db),
):
    return replace_connector_endpoints(db, endpoints)


@external_router.get("/settings/alert-rules", response_model=list[AlertRule])
def get_settings_alert_rules(db: Session = Depends(get_db)):
    return build_alert_rule_responses(db)


@external_router.put("/settings/alert-rules", response_model=list[AlertRule])
def update_settings_alert_rules(
    rules: list[AlertRule],
    db: Session = Depends(get_db),
):
    return replace_alert_rules(db, rules)


@external_router.get("/settings/alert-rule-options", response_model=AlertRuleOptionCatalog)
def get_settings_alert_rule_options(db: Session = Depends(get_db)):
    return build_alert_rule_options_response(db)


@external_router.get(
    "/settings/telegram-trigger-subscriptions",
    response_model=list[TelegramTriggerSubscription],
)
def get_settings_telegram_trigger_subscriptions(db: Session = Depends(get_db)):
    return build_telegram_trigger_subscription_responses(db)


@external_router.put(
    "/settings/telegram-trigger-subscriptions",
    response_model=list[TelegramTriggerSubscription],
)
def update_settings_telegram_trigger_subscriptions(
    subscriptions: list[TelegramTriggerSubscription],
    db: Session = Depends(get_db),
):
    return replace_telegram_trigger_subscriptions(db, subscriptions)


@external_router.post(
    "/settings/telegram-trigger-subscriptions/test",
    response_model=TelegramTriggerTestResponse,
)
def test_settings_telegram_trigger_subscription(
    subscription: TelegramTriggerSubscription,
):
    try:
        send_test_telegram_trigger_message(subscription)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return TelegramTriggerTestResponse(
        status="sent",
        detail="Telegram test message sent.",
    )


@external_router.get(
    "/settings/apple-message-trigger-subscriptions",
    response_model=list[AppleMessageTriggerSubscription],
)
def get_settings_apple_message_trigger_subscriptions(db: Session = Depends(get_db)):
    return build_apple_message_trigger_subscription_responses(db)


@external_router.put(
    "/settings/apple-message-trigger-subscriptions",
    response_model=list[AppleMessageTriggerSubscription],
)
def update_settings_apple_message_trigger_subscriptions(
    subscriptions: list[AppleMessageTriggerSubscription],
    db: Session = Depends(get_db),
):
    return replace_apple_message_trigger_subscriptions(db, subscriptions)


@external_router.post(
    "/settings/apple-message-trigger-subscriptions/test",
    response_model=AppleMessageTriggerTestResponse,
)
def test_settings_apple_message_trigger_subscription(
    subscription: AppleMessageTriggerSubscription,
):
    try:
        send_test_apple_message_trigger_message(subscription)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AppleMessageTriggerTestResponse(
        status="sent",
        detail="Apple Messages test message sent.",
    )


@external_router.get(
    "/settings/claude-api-connectors",
    response_model=list[ClaudeApiConnectorEndpoint],
)
def get_settings_claude_api_connectors(db: Session = Depends(get_db)):
    return build_claude_api_connector_responses(db)


@external_router.put(
    "/settings/claude-api-connectors",
    response_model=list[ClaudeApiConnectorEndpoint],
)
def update_settings_claude_api_connectors(
    endpoints: list[ClaudeApiConnectorEndpoint],
    db: Session = Depends(get_db),
):
    return replace_claude_api_connectors(db, endpoints)


@external_router.post(
    "/settings/claude-api-connectors/test",
    response_model=ClaudeApiConnectorTestResponse,
)
def test_settings_claude_api_connector(endpoint: ClaudeApiConnectorEndpoint):
    config = {
        "base_url": endpoint.base_url,
        "auth_token": endpoint.auth_token,
        "timeout_seconds": endpoint.timeout_seconds,
        "retry_count": endpoint.retry_count,
    }
    if endpoint.id is not None:
        with SessionLocal() as db:
            existing_row = (
                db.query(SQLModels.ConnectorEndpoint)
                .filter_by(
                    id=endpoint.id,
                    connector_key=CONNECTOR_KEY_CLAUDE_API,
                    is_deleted=False,
                )
                .first()
            )
            if existing_row is not None:
                config = merge_connector_endpoint_secret_config(
                    get_connector_endpoint_config(existing_row),
                    config,
                )
    row = SQLModels.ConnectorEndpoint(
        connector_key=CONNECTOR_KEY_CLAUDE_API,
        enabled=endpoint.enabled,
        label=endpoint.connector_label,
        config_json=json.dumps(config),
        delivery_capabilities_json=json.dumps(["json", "sync", "retry"]),
    )
    try:
        payload = build_claude_trigger_payload(
            trigger_id="TEST-TRIGGER",
            trigger_type="MANUAL",
            trigger_text="Hearthlight test trigger payload",
            display_title="Connector Test",
            alert_level="Low",
            metadata={"purpose": "claude api connector test"},
        )
        send_claude_api_payload(row, payload)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ClaudeApiConnectorTestResponse(
        status="sent",
        detail="Third-party API test payload sent.",
    )


@external_router.post("/demo/triggers/fire", response_model=DemoTriggerFireResponse)
def fire_demo_trigger(
    payload: DemoTriggerFireRequest,
    db: Session = Depends(get_db),
):
    from ...shared.database.database_worker import DatabaseWorker

    worker = DatabaseWorker()
    worker.db = db
    worker.queue_trigger_notifications(
        SQLModels.Incident(
            id=0,
            incident_type=payload.trigger_key.replace("_trigger", "").upper(),
            status="DEMO",
            camera_id=None,
            zone_id=None,
            timestamp=time.time(),
            created_at=datetime.utcnow(),
        ),
        display_title=payload.display_title,
        source_id=payload.source_id,
        alert_level=payload.alert_level.title(),
        metadata={"demo": True, **dict(payload.metadata or {})},
        trigger_key=payload.trigger_key,
        delivery_target_ids=payload.delivery_target_ids,
    )
    return DemoTriggerFireResponse(status="sent", detail="Demo trigger queued.")


@external_router.get("/sources/{source_id}/preview.mjpeg")
async def get_source_preview(source_id: int, request: Request, db: Session = Depends(get_db)):
    source_row = get_source_row_by_id(source_id, db)
    if is_hybrid_local_cpu_runtime():
        upload_path = None
        if source_row.upload_id is not None:
            upload_row = get_upload_rows_by_id(db, [source_row.upload_id]).get(source_row.upload_id)
            upload_path = upload_row.stored_path if upload_row is not None else None
        query = {
            "kind": source_row.kind,
            "source_value": format_source_value_for_query(
                coerce_source_value_for_api(source_row),
            ),
        }
        host_upload_path = build_host_upload_path(upload_path)
        if host_upload_path:
            query["upload_path"] = host_upload_path
        preview_url = build_local_worker_url("/preview.mjpeg") + "?" + urllib_parse.urlencode(query)
        try:
            upstream_response = urllib_request.urlopen(
                preview_url,
                timeout=LOCAL_WORKER_REQUEST_TIMEOUT_SECONDS,
            )
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore").strip()
            raise HTTPException(
                status_code=503,
                detail=detail or "source preview could not be opened on local worker",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="source preview could not be opened on local worker",
            ) from exc

        async def proxy_stream():
            try:
                with upstream_response as response:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        if await request.is_disconnected():
                            break
                        yield chunk
            except Exception:
                logger.exception("Failed to proxy local worker preview stream")

        return StreamingResponse(
            proxy_stream(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )
    preview_candidates = resolve_preview_source_candidates(source_row, db)
    prefer_live_edge_seek = source_row.kind != SOURCE_KIND_VIDEO_UPLOAD

    capture = None
    preview_source = None
    is_local_file = False
    for candidate, candidate_is_local_file in preview_candidates:
        candidate_capture = cv2.VideoCapture()
        configure_capture_timeouts(candidate_capture, SOURCE_PREVIEW_TIMEOUT_MS)
        opened = open_capture(candidate_capture, candidate)
        if opened and candidate_capture.isOpened():
            capture = candidate_capture
            preview_source = candidate
            is_local_file = candidate_is_local_file
            break
        candidate_capture.release()

    if capture is None or preview_source is None:
        raise HTTPException(status_code=503, detail="source preview could not be opened")

    def seek_to_live_edge():
        if not is_local_file or not prefer_live_edge_seek:
            return
        try:
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            if frame_count > 2:
                capture.set(cv2.CAP_PROP_POS_FRAMES, frame_count - 2)
        except Exception:
            logger.debug("Failed to seek preview capture to live edge", exc_info=True)

    seek_to_live_edge()

    async def frame_stream():
        nonlocal capture
        try:
            while True:
                if await request.is_disconnected():
                    break
                has_frame, frame = capture.read()
                if not has_frame or frame is None:
                    if not is_local_file:
                        break
                    capture.release()
                    await asyncio.sleep(0.15)
                    reopened_capture = cv2.VideoCapture()
                    configure_capture_timeouts(reopened_capture, SOURCE_PREVIEW_TIMEOUT_MS)
                    reopened = open_capture(reopened_capture, preview_source)
                    if not reopened or not reopened_capture.isOpened():
                        reopened_capture.release()
                        continue
                    capture = reopened_capture
                    seek_to_live_edge()
                    continue
                encoded_frame = encode_preview_frame(frame)
                if encoded_frame is None:
                    continue
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + encoded_frame
                    + b"\r\n"
                )
                await asyncio.sleep(SOURCE_PREVIEW_FRAME_DELAY_SECONDS)
        finally:
            capture.release()

    return StreamingResponse(
        frame_stream(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )


@external_router.post("/sources/uploads", response_model=UploadResponse)
async def upload_source_video(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    return await store_uploaded_source_video(file, db)


@external_router.post("/settings/input-sources/uploads", response_model=UploadResponse)
async def upload_settings_input_source_video(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    return await store_uploaded_source_video(file, db)


@external_router.delete("/sources/uploads/{upload_id}")
def delete_uploaded_source(upload_id: int, db: Session = Depends(get_db)):
    return delete_uploaded_source_record(upload_id, db)


@external_router.delete("/settings/input-sources/uploads/{upload_id}")
def delete_settings_uploaded_source(upload_id: int, db: Session = Depends(get_db)):
    return delete_uploaded_source_record(upload_id, db)


@external_router.get("/system/resources", response_model=ResourceSnapshot)
def get_system_resources(db: Session = Depends(get_db)):
    snapshot = get_current_resource_snapshot(db)
    return ResourceSnapshot.model_validate(snapshot)


@external_router.get("/system/model-health", response_model=dict[str, ModelHealth])
def get_system_model_health(db: Session = Depends(get_db)):
    source_rows = get_active_source_rows(db)
    bundle = get_registry_bundle(db, source_rows=source_rows)
    snapshot = get_current_resource_snapshot(db)
    return {
        model_key: ModelHealth.model_validate(model_health)
        for model_key, model_health in build_model_health(
            bundle,
            has_gpu=bool(snapshot.get("gpus")),
        ).items()
    }


@external_router.get("/models", response_model=list[ModelRegistration])
def get_models(db: Session = Depends(get_db)):
    source_rows = get_active_source_rows(db)
    bundle = get_registry_bundle(db, source_rows=source_rows)
    return build_model_registration_responses(bundle)


@external_router.get("/models/{stage}", response_model=list[ModelRegistration])
def get_models_by_stage(stage: str, db: Session = Depends(get_db)):
    normalized_stage = normalize_binding_stage(stage)
    source_rows = get_active_source_rows(db)
    bundle = get_registry_bundle(db, source_rows=source_rows)
    return [
        registration
        for registration in build_model_registration_responses(bundle)
        if registration.stage == normalized_stage
    ]


@external_router.get("/model-options", response_model=ModelOptionCatalog)
def get_model_options(db: Session = Depends(get_db)):
    source_rows = get_active_source_rows(db)
    bundle = get_registry_bundle(db, source_rows=source_rows)
    return ModelOptionCatalog.model_validate(build_model_option_catalog(bundle))


@external_router.get("/model-logs", response_model=ModelResultLogPage)
def get_model_logs(
    page: int = 1,
    page_size: int = 20,
    stage: str | None = None,
    source_id: int | None = None,
    result_query: str | None = None,
    run_identifier: str | None = None,
    db: Session = Depends(get_db),
):
    return build_model_result_log_page(
        db,
        page=page,
        page_size=page_size,
        stage=stage,
        source_id=source_id,
        result_query=result_query,
        run_identifier=run_identifier,
    )


@external_router.get("/model-bindings", response_model=list[ModelBinding])
def get_model_bindings(db: Session = Depends(get_db)):
    source_rows = get_active_source_rows(db)
    bundle = get_registry_bundle(db, source_rows=source_rows)
    snapshot = get_current_resource_snapshot(db)
    return build_model_binding_responses(
        bundle,
        source_rows,
        has_gpu=bool(snapshot.get("gpus")),
    )


@external_router.get("/mounted-models", response_model=list[MountedModelStage])
def get_mounted_models(db: Session = Depends(get_db)):
    source_rows = get_active_source_rows(db)
    bundle = get_registry_bundle(db, source_rows=source_rows)
    return build_mounted_model_stage_responses(bundle)


@external_router.put("/model-bindings", response_model=list[ModelBinding])
def update_model_bindings(bindings: list[ModelBinding], db: Session = Depends(get_db)):
    source_rows = get_active_source_rows(db)
    source_by_id = {row.id: row for row in source_rows}
    bundle = get_registry_bundle(db, source_rows=source_rows)
    defaults = build_default_bindings(bundle)
    mounted_models = build_effective_mounted_models(bundle, bundle.get("mounted_models"))

    for binding in bindings:
        stage = normalize_binding_stage(binding.stage)
        if stage not in OPERATOR_MODEL_STAGES:
            raise HTTPException(status_code=400, detail=f"{stage} is not editable in this workspace")
        if binding.model_key is not None:
            registration = get_registration(bundle, stage, binding.model_key)
            if registration is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"unknown {stage} model binding {binding.model_key}",
                )
            ensure_mounted_model_key(bundle, mounted_models, stage, binding.model_key)
        if binding.binding_scope == "source" or binding.source_id is not None:
            if binding.source_id not in source_by_id:
                raise HTTPException(status_code=404, detail="source binding target not found")
            setattr(source_by_id[binding.source_id], get_stage_field_name(stage), binding.model_key)
        else:
            defaults[stage] = binding.model_key

    persist_model_bindings(defaults)
    persist_mounted_models(mounted_models)
    db.commit()
    refreshed_sources = get_active_source_rows(db)
    refreshed_bundle = get_registry_bundle(db, source_rows=refreshed_sources)
    snapshot = get_current_resource_snapshot(db)
    return build_model_binding_responses(
        refreshed_bundle,
        refreshed_sources,
        has_gpu=bool(snapshot.get("gpus")),
    )


@external_router.put("/mounted-models", response_model=list[MountedModelStage])
def update_mounted_models(stages: list[MountedModelStage], db: Session = Depends(get_db)):
    source_rows = get_active_source_rows(db)
    bundle = get_registry_bundle(db, source_rows=source_rows)
    mounted_models = {stage: [] for stage in OPERATOR_MODEL_STAGES}
    for stage_entry in stages:
        if stage_entry.stage not in OPERATOR_MODEL_STAGES:
            raise HTTPException(status_code=400, detail=f"{stage_entry.stage} is not mountable in this workspace")
        mounted_models[stage_entry.stage] = []
        for model_key in stage_entry.mounted_model_keys:
            registration = get_registration(bundle, stage_entry.stage, model_key)
            if registration is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"unknown {stage_entry.stage} model binding {model_key}",
                )
            ensure_mounted_model_key(bundle, mounted_models, stage_entry.stage, model_key)

    defaults = build_default_bindings(bundle)
    required = collect_required_mounted_models(bundle, source_rows, defaults=defaults)
    missing_by_stage = {}
    for stage, required_keys in required.items():
        missing = sorted(required_keys.difference(set(mounted_models.get(stage) or [])))
        if missing:
            missing_by_stage[stage] = missing
    if missing_by_stage:
        formatted = "; ".join(
            f"{stage}: {', '.join(keys)}"
            for stage, keys in missing_by_stage.items()
        )
        raise HTTPException(
            status_code=400,
            detail=f"cannot unmount models currently in use: {formatted}",
        )

    persist_mounted_models(mounted_models)
    refreshed_bundle = get_registry_bundle(db, source_rows=source_rows)
    return build_mounted_model_stage_responses(refreshed_bundle)


@external_router.get("/monitoring/runs", response_model=list[RunSummary])
def get_monitoring_runs(db: Session = Depends(get_db), limit: int | None = None):
    refresh_runtime_status()
    return build_run_summaries(db, limit)


@external_router.get("/monitoring/events", response_model=list[ResourceEventRecord])
def get_monitoring_events(db: Session = Depends(get_db), limit: int | None = None):
    refresh_runtime_status()
    return build_resource_event_records(db, limit)


@external_router.get("/monitoring/overview", response_model=MonitoringOverview)
def get_monitoring_overview(
    db: Session = Depends(get_db),
    run_identifier: str | None = None,
    limit: int | None = None,
):
    current_status = refresh_runtime_status()
    selected_run = get_run_row(db, run_identifier)
    snapshot = get_current_resource_snapshot(db)
    source_rows = get_active_source_rows(db)
    registry_bundle = get_registry_bundle(db, source_rows=source_rows)
    return MonitoringOverview(
        generated_at=utc_now_iso(),
        system_status=current_status,
        current_run_id=run_id,
        selected_run_identifier=(
            selected_run.run_identifier if selected_run is not None else None
        ),
        runs=build_run_summaries(db),
        resources=ResourceSnapshot.model_validate(snapshot),
        admission=AdmissionStatus.model_validate(snapshot["admission"]),
        sources=build_source_responses(db, snapshot),
        model_bindings=build_model_binding_responses(
            registry_bundle,
            source_rows,
            has_gpu=bool(snapshot.get("gpus")),
        ),
        model_registrations=build_model_registration_responses(registry_bundle),
        latest_incidents=build_incident_feed_items(db, selected_run, limit=limit),
        latest_entities=build_entity_feed_items(db, selected_run, limit=limit),
        latest_anomalies=build_anomaly_feed_items(db, selected_run, limit=limit),
        recent_events=[
            ResourceEventRecord.model_validate(item)
            for item in (
                list_connector_delivery_events(limit)
                + [event.model_dump() for event in build_resource_event_records(db, limit)]
            )[: (limit or 20)]
        ],
        feed_endpoints=[
            FeedEndpoint.model_validate(item) for item in build_feed_endpoint_catalog()
        ],
    )


@external_router.get("/feeds/incidents", response_model=list[AlgorithmIncidentFeedItem])
def get_incident_feed(
    db: Session = Depends(get_db),
    run_identifier: str | None = None,
    limit: int | None = None,
):
    refresh_runtime_status()
    selected_run = get_run_row(db, run_identifier)
    return build_incident_feed_items(db, selected_run, limit=limit)


@external_router.get("/feeds/entities", response_model=list[AlgorithmEntityFeedItem])
def get_entity_feed(
    db: Session = Depends(get_db),
    run_identifier: str | None = None,
    limit: int | None = None,
):
    refresh_runtime_status()
    selected_run = get_run_row(db, run_identifier)
    return build_entity_feed_items(db, selected_run, limit=limit)


@external_router.get("/feeds/algorithm", response_model=AlgorithmFeed)
def get_algorithm_feed(
    db: Session = Depends(get_db),
    run_identifier: str | None = None,
    limit: int | None = None,
):
    return build_algorithm_feed_payload(
        db,
        run_identifier=run_identifier,
        limit=limit,
    )


@external_router.post("/system/modules/{module_name}/restart")
def restart_module(module_name: str, db: Session = Depends(get_db)):
    normalized_module = normalize_module_name(module_name)
    if run_id is None:
        raise HTTPException(status_code=409, detail="system is not running")
    runtime_cfg, source_rows = build_runtime_cfg(db, run_id)
    target_modules = [normalized_module]
    try:
        publish_system_message(
            DataModels.SystemMessage(
                command=DataModels.SystemCommand.STOP,
                target_modules=target_modules,
            )
        )
        time.sleep(MODULE_RESTART_DELAY_SEC)
        publish_system_message(
            DataModels.SystemMessage(
                command=DataModels.SystemCommand.START,
                config=runtime_cfg,
                target_modules=target_modules,
            )
        )
        log_resource_event(
            PersistedEvent(
                event_type="module_restart",
                severity="info",
                message=f"module restart requested for {normalized_module}",
                metadata={
                    "module": normalized_module,
                    "run_id": run_id,
                    "enabled_sources": len(source_rows),
                },
            )
        )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        logger.exception("Failed to restart module %s", normalized_module)
        raise HTTPException(status_code=503, detail="failed to restart module") from exc
    return {"status": "restarting", "module": normalized_module}


@external_router.post("/camera_stream", response_model=list[InputSource])
def update_camera_streams(cameras: list[Camera], db: Session = Depends(get_db)):
    if not cameras:
        raise HTTPException(status_code=400, detail="at least one camera is required")
    sources = []
    for order, camera in enumerate(cameras):
        kind = SOURCE_KIND_WEBCAM if isinstance(camera.source, int) else SOURCE_KIND_CAMERA_URL
        label = camera.name or f"Source {order + 1}"
        sources.append(
            InputSource(
                kind=kind,
                label=label,
                tasks=camera.tasks,
                enabled=True,
                order=order,
                source_value=camera.source,
            )
        )
    replace_sources(db, sources)
    snapshot = get_current_resource_snapshot(db)
    return build_source_responses(db, snapshot)


@external_router.get("/camera_streams")
def get_active_camera_streams(db: Session = Depends(get_db)):
    source_rows = get_active_source_rows(db)
    upload_rows = get_upload_rows_by_id(
        db, [row.upload_id for row in source_rows if row.upload_id is not None]
    )
    streams = []
    for row in source_rows:
        source = coerce_source_value_for_api(row)
        if row.kind == SOURCE_KIND_VIDEO_UPLOAD and row.upload_id is not None:
            upload_row = upload_rows.get(row.upload_id)
            source = upload_row.stored_path if upload_row is not None else None
        if source is None:
            continue
        streams.append(Camera(name=row.label, tasks=list(row.tasks), source=source))
    return streams


@external_router.post("/register_poi")
async def register_poi(poi: POISearch, db: Session = Depends(get_db)):
    if run_id is None:
        raise HTTPException(status_code=409, detail="system is not running")
    run = db.query(SQLModels.Run).filter_by(run_identifier=run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="no current run found")
    if poi.research:
        db_search = (
            db.query(SQLModels.POISearch)
            .filter_by(name=poi.name, run_id=run.id)
            .first()
        )
        if db_search is None:
            raise HTTPException(
                status_code=404, detail=f"poi with name {poi.name} not found"
            )
        message = DataModels.POISearch(search_id=db_search.id)
    else:
        if not poi.images:
            raise HTTPException(status_code=400, detail="poi images are required")
        if len(poi.images) > MAX_POI_IMAGES:
            raise HTTPException(
                status_code=400,
                detail=f"poi image limit exceeded; max is {MAX_POI_IMAGES}",
            )
        crop_dir = resolve_safe_child_path(POI_CROP_DIR, poi.name, fallback="poi")
        mean_feature = process_images(poi.images, save_dir=crop_dir)
        db_search = SQLModels.POISearch(
            name=poi.name, run_id=run.id, crop_dir=str(crop_dir)
        )
        try:
            db.add(db_search)
            db.flush()
            db.refresh(db_search)
            message = DataModels.POISearch(feature=mean_feature, search_id=db_search.id)
            get_poi_publisher().publish_item(message)
            db.commit()
        except Exception as exc:
            db.rollback()
            if isinstance(exc, HTTPException):
                raise
            if isinstance(exc, SQLAlchemyError):
                logger.exception("Failed to persist POI search")
                raise HTTPException(
                    status_code=500, detail="failed to save poi search"
                ) from exc
            logger.exception("Failed to publish POI search")
            raise HTTPException(
                status_code=503, detail="failed to publish poi search"
            ) from exc
        return {"status": f"POI registered: {poi.name}"}
    try:
        get_poi_publisher().publish_item(message)
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        logger.exception("Failed to publish POI research request")
        raise HTTPException(status_code=503, detail="failed to publish poi search") from exc
    return {"status": f"POI registered: {poi.name}"}
