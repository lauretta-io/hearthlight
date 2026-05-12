"""
This file contains the Pydantic models for the API endpoints defined in external_router.
"""

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def validate_non_empty_string(value: str, field_name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} cannot be empty")
    return value


SOURCE_KIND_CAMERA_URL = "camera_url"
SOURCE_KIND_VIDEO_UPLOAD = "video_upload"
SOURCE_KIND_WEBCAM = "webcam"
SOURCE_KINDS = {
    SOURCE_KIND_CAMERA_URL,
    SOURCE_KIND_VIDEO_UPLOAD,
    SOURCE_KIND_WEBCAM,
}
MODEL_BINDING_STAGES = {
    "detector",
    "tracker",
    "reid",
    "anomaly_stage_1",
    "anomaly_stage_2",
}
ALERT_SIGNAL_FAMILIES = {
    "detector",
    "anomaly_object",
    "anomaly_activity",
}
ALERT_LEVELS = {
    "low",
    "medium",
    "high",
}


def normalize_source_kind(value: str) -> str:
    normalized = validate_non_empty_string(value, "kind").lower().replace("-", "_")
    if normalized not in SOURCE_KINDS:
        raise ValueError(
            "kind must be one of camera_url, video_upload, webcam"
        )
    return normalized


class Camera(BaseModel):
    tasks: List[str] = Field(min_length=1)
    source: str | int
    name: str | None = Field(default=None, max_length=255)

    @field_validator("tasks", mode="before")
    def normalize_tasks(cls, value):
        if not isinstance(value, list) or not value:
            raise ValueError("tasks must contain at least one item")
        normalized = []
        for task in value:
            task = validate_non_empty_string(str(task), "task").upper()
            normalized.append(task)
        return normalized

    @field_validator("source")
    def validate_source(cls, value):
        if isinstance(value, str):
            return validate_non_empty_string(value, "source")
        return value

    @field_validator("name")
    def validate_name(cls, value):
        if value is None:
            return value
        return validate_non_empty_string(value, "name")


class UploadedMedia(BaseModel):
    id: int
    original_filename: str
    stored_path: str
    checksum_sha256: str
    size_bytes: int
    lifecycle_state: str


class InputSource(BaseModel):
    id: int | None = None
    kind: str
    label: str = Field(max_length=255)
    tasks: List[str] = Field(min_length=1)
    enabled: bool = True
    order: int = Field(ge=0, default=0)
    source_value: str | int | None = None
    upload_id: int | None = None
    upload: UploadedMedia | None = None
    detector_model_key: str | None = None
    tracker_model_key: str | None = None
    reid_model_key: str | None = None
    anomaly_stage_1_model_key: str | None = None
    anomaly_stage_2_model_key: str | None = None
    state: str = "idle"
    frames_processed: int | None = None
    total_frames: int | None = None
    fps: float | None = None
    last_error: str | None = None
    last_activity_at: str | None = None

    @field_validator("kind")
    def validate_kind(cls, value):
        return normalize_source_kind(value)

    @field_validator("label")
    def validate_label(cls, value):
        return validate_non_empty_string(value, "label")

    @field_validator("tasks", mode="before")
    def normalize_tasks(cls, value):
        if not isinstance(value, list) or not value:
            raise ValueError("tasks must contain at least one item")
        normalized = []
        for task in value:
            normalized.append(validate_non_empty_string(str(task), "task").upper())
        return normalized

    @field_validator("source_value")
    def validate_source_value(cls, value):
        if value is None:
            return value
        if isinstance(value, str):
            return validate_non_empty_string(value, "source_value")
        return value

    @model_validator(mode="after")
    def validate_shape(self):
        if self.kind == SOURCE_KIND_VIDEO_UPLOAD:
            if self.upload_id is None:
                raise ValueError("upload_id is required for video_upload sources")
        elif self.kind == SOURCE_KIND_WEBCAM:
            if self.source_value is None:
                raise ValueError("source_value is required for webcam sources")
            if isinstance(self.source_value, str):
                try:
                    self.source_value = int(self.source_value)
                except ValueError as exc:
                    raise ValueError(
                        "webcam source_value must be an integer device index"
                    ) from exc
        else:
            if self.source_value is None:
                raise ValueError("source_value is required for camera_url sources")
        return self


class GpuResource(BaseModel):
    index: int
    name: str
    utilization_percent: float | None = None
    memory_used_mb: float | None = None
    memory_total_mb: float | None = None


class DependencyHealth(BaseModel):
    status: str
    detail: str | None = None


class ModuleRuntimeMetrics(BaseModel):
    state: str = "ok"
    max_queue_depth: int = 0
    hottest_queue: str | None = None
    queue_depths: dict[str, int] = Field(default_factory=dict)


class ModelRegistration(BaseModel):
    model_key: str
    display_name: str | None = None
    stage: str
    adapter: str
    artifact_ref: str | None = None
    runtime: dict = Field(default_factory=dict)
    capabilities: dict = Field(default_factory=dict)
    healthcheck: dict = Field(default_factory=dict)
    requires_gpu: bool = False
    resource_profile: dict = Field(default_factory=dict)
    source_path: str | None = None


class ModelOption(BaseModel):
    model_key: str
    display_name: str
    stage: str
    adapter: str
    artifact_ref: str | None = None
    runtime: dict = Field(default_factory=dict)
    capabilities: dict = Field(default_factory=dict)
    healthcheck: dict = Field(default_factory=dict)
    requires_gpu: bool = False
    resource_profile: dict = Field(default_factory=dict)
    source_path: str | None = None
    option_origin: str
    comes_from_model_zoo: bool = False
    overrides_model_zoo: bool = False


class ModelOptionStage(BaseModel):
    stage: str
    options: list[ModelOption] = Field(default_factory=list)
    model_zoo_option_count: int = 0
    local_option_count: int = 0
    local_override_count: int = 0


class ModelZooSource(BaseModel):
    package_name: str
    version: str | None = None
    repository_url: str | None = None
    commit_sha: str | None = None
    commit_short: str | None = None
    resolved_from: str | None = None
    catalog_available: bool = False


class ModelOptionCatalog(BaseModel):
    model_zoo: ModelZooSource
    stages: list[ModelOptionStage] = Field(default_factory=list)


class ModelBinding(BaseModel):
    stage: str
    model_key: str | None = None
    source_id: int | None = None
    binding_scope: str = "default"

    @field_validator("stage")
    def validate_stage(cls, value):
        normalized = validate_non_empty_string(value, "stage").lower()
        if normalized not in MODEL_BINDING_STAGES:
            raise ValueError(
                "stage must be one of detector, tracker, reid, anomaly_stage_1, anomaly_stage_2"
            )
        return normalized


class ModelHealth(BaseModel):
    model_key: str
    stage: str
    adapter: str
    healthy: bool
    detail: str | None = None
    requires_gpu: bool = False


class AssetReference(BaseModel):
    uri: str
    media_type: str
    checksum_sha256: str | None = None
    size_bytes: int | None = None
    producer: str | None = None
    timestamp: str | None = None


class AnomalyEvent(BaseModel):
    event_id: str
    run_id: str | None = None
    source_id: int | None = None
    camera_id: int | None = None
    frame_id: int | None = None
    event_time: str | None = None
    title: str | None = None
    stage_1_model_key: str | None = None
    stage_2_model_key: str | None = None
    model_key: str
    category: str
    score: float
    reasoning: str | None = None
    visible_items: list[str] = Field(default_factory=list)
    visible_activities: list[str] = Field(default_factory=list)
    asset_references: list[AssetReference] = Field(default_factory=list)


class MicroBatchEnvelope(BaseModel):
    generated_at: str
    run_identifier: str | None = None
    batch_type: str
    record_count: int
    sink_key: str
    records: list[dict] = Field(default_factory=list)
    asset_references: list[AssetReference] = Field(default_factory=list)


class AdmissionStatus(BaseModel):
    allowed: bool
    reason: str | None = None
    thresholds: dict[str, float | None] | None = None
    source_errors: list[str] = Field(default_factory=list)
    dependency_errors: list[str] = Field(default_factory=list)


class GpuResourceDrift(BaseModel):
    index: int
    utilization_delta_percent: float | None = None
    memory_delta_mb: float | None = None


class ResourceDrift(BaseModel):
    state: str = "baseline"
    cpu_percent_delta: float | None = None
    memory_percent_delta: float | None = None
    disk_percent_delta: float | None = None
    gpu_deltas: list[GpuResourceDrift] = Field(default_factory=list)
    alerts: list[str] = Field(default_factory=list)
    thresholds: dict[str, float | None] | None = None


class ResourceSnapshot(BaseModel):
    cpu_percent: float | None = None
    memory_percent: float | None = None
    disk_percent: float | None = None
    gpus: list[GpuResource] = Field(default_factory=list)
    module_status: dict[str, str] = Field(default_factory=dict)
    module_metrics: dict[str, ModuleRuntimeMetrics] = Field(default_factory=dict)
    dependency_status: dict[str, DependencyHealth] = Field(default_factory=dict)
    model_health: dict[str, ModelHealth] = Field(default_factory=dict)
    admission: AdmissionStatus | None = None
    drift: ResourceDrift | None = None
    updated_at: str | None = None


class UploadResponse(BaseModel):
    upload: UploadedMedia


class AnomalyItemSetting(BaseModel):
    item: str
    trigger_score: int = Field(ge=1, le=10)

    @field_validator("item")
    def validate_item(cls, value):
        return validate_non_empty_string(value, "item")


class AnomalyPromptSettings(BaseModel):
    anomaly_items: list[AnomalyItemSetting] = Field(default_factory=list)
    anomaly_behaviors: list[str] = Field(default_factory=list)

    @field_validator("anomaly_behaviors", mode="before")
    def validate_anomaly_behaviors(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("anomaly_behaviors must be a list")
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            label = validate_non_empty_string(str(item), "anomaly_behavior")
            lowered = label.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append(label)
        return normalized


class AlertRule(BaseModel):
    id: int | None = None
    source_id: int
    enabled: bool = True
    rule_label: str | None = Field(default=None, max_length=255)
    signal_family: str
    target_key: str
    min_confidence: float = Field(ge=0.0, le=1.0)
    alert_level: str
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("source_id")
    def validate_source_id(cls, value):
        if value <= 0:
            raise ValueError("source_id must be a positive integer")
        return value

    @field_validator("rule_label")
    def validate_rule_label(cls, value):
        if value is None:
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("signal_family")
    def validate_signal_family(cls, value):
        normalized = validate_non_empty_string(value, "signal_family").lower()
        if normalized not in ALERT_SIGNAL_FAMILIES:
            raise ValueError(
                "signal_family must be one of detector, anomaly_object, anomaly_activity"
            )
        return normalized

    @field_validator("target_key")
    def validate_target_key(cls, value):
        return validate_non_empty_string(value, "target_key")

    @field_validator("alert_level")
    def validate_alert_level(cls, value):
        normalized = validate_non_empty_string(value, "alert_level").lower()
        if normalized not in ALERT_LEVELS:
            raise ValueError("alert_level must be one of low, medium, high")
        return normalized


class AlertRuleOption(BaseModel):
    key: str
    label: str


class AlertRuleSignalOptions(BaseModel):
    signal_family: str
    options: list[AlertRuleOption] = Field(default_factory=list)
    unavailable_reason: str | None = None


class AlertRuleSourceOptions(BaseModel):
    source_id: int
    source_label: str
    detector_model_key: str | None = None
    anomaly_stage_1_model_key: str | None = None
    anomaly_stage_2_model_key: str | None = None
    signal_options: list[AlertRuleSignalOptions] = Field(default_factory=list)


class AlertRuleOptionCatalog(BaseModel):
    sources: list[AlertRuleSourceOptions] = Field(default_factory=list)


class TelegramTriggerSubscription(BaseModel):
    id: int | None = None
    enabled: bool = True
    subscription_label: str | None = Field(default=None, max_length=255)
    bot_token: str
    chat_id: str
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("subscription_label")
    def validate_subscription_label(cls, value):
        if value is None:
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("bot_token")
    def validate_bot_token(cls, value):
        return validate_non_empty_string(value, "bot_token")

    @field_validator("chat_id")
    def validate_chat_id(cls, value):
        return validate_non_empty_string(value, "chat_id")


class TelegramTriggerTestResponse(BaseModel):
    status: str
    detail: str | None = None


class AppleMessageTriggerSubscription(BaseModel):
    id: int | None = None
    enabled: bool = True
    subscription_label: str | None = Field(default=None, max_length=255)
    recipient_handle: str
    service: str = "iMessage"
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("subscription_label")
    def validate_apple_subscription_label(cls, value):
        if value is None:
            return value
        stripped = value.strip()
        return stripped or None

    @field_validator("recipient_handle")
    def validate_apple_recipient_handle(cls, value):
        return validate_non_empty_string(value, "recipient_handle")

    @field_validator("service")
    def validate_apple_service(cls, value):
        normalized = validate_non_empty_string(value, "service")
        if normalized not in {"iMessage", "SMS"}:
            raise ValueError("service must be iMessage or SMS")
        return normalized


class AppleMessageTriggerTestResponse(BaseModel):
    status: str
    detail: str | None = None


class FeedLocation(BaseModel):
    camera_id: int | None = None
    zone_id: int | None = None


class RunSummary(BaseModel):
    run_identifier: str
    start_time: str | None = None
    status: str
    incident_count: int = 0
    entity_count: int = 0
    source_count: int = 0
    camera_count: int = 0


class AlgorithmIncidentFeedItem(BaseModel):
    run_identifier: str
    incident_id: str
    incident_type: str
    display_title: str | None = None
    alert_level: str | None = None
    metadata: dict[str, str | float | int | None] = Field(default_factory=dict)
    status: str
    incident_time: str | None = None
    last_update_time: str | None = None
    last_updated_by: str | None = None
    location: FeedLocation | None = None


class AlgorithmEntityFeedItem(BaseModel):
    run_identifier: str
    entity_id: str
    entity_type: str
    last_seen_time: str | None = None
    location: FeedLocation | None = None
    associated_incident_ids: list[str] = Field(default_factory=list)


class ResourceEventRecord(BaseModel):
    created_at: str
    event_type: str
    severity: str
    message: str
    metadata: dict | list | None = None


class FeedEndpoint(BaseModel):
    name: str
    path: str
    description: str


class MonitoringOverview(BaseModel):
    generated_at: str
    system_status: str
    current_run_id: str | None = None
    selected_run_identifier: str | None = None
    runs: list[RunSummary] = Field(default_factory=list)
    resources: ResourceSnapshot | None = None
    admission: AdmissionStatus | None = None
    sources: list[InputSource] = Field(default_factory=list)
    model_bindings: list[ModelBinding] = Field(default_factory=list)
    model_registrations: list[ModelRegistration] = Field(default_factory=list)
    latest_incidents: list[AlgorithmIncidentFeedItem] = Field(default_factory=list)
    latest_entities: list[AlgorithmEntityFeedItem] = Field(default_factory=list)
    latest_anomalies: list[AnomalyEvent] = Field(default_factory=list)
    recent_events: list[ResourceEventRecord] = Field(default_factory=list)
    feed_endpoints: list[FeedEndpoint] = Field(default_factory=list)


class AlgorithmFeed(BaseModel):
    generated_at: str
    run_identifier: str | None = None
    current_run_id: str | None = None
    system_status: str
    resources: ResourceSnapshot | None = None
    admission: AdmissionStatus | None = None
    sources: list[InputSource] = Field(default_factory=list)
    model_bindings: list[ModelBinding] = Field(default_factory=list)
    incidents: list[AlgorithmIncidentFeedItem] = Field(default_factory=list)
    entities: list[AlgorithmEntityFeedItem] = Field(default_factory=list)
    anomalies: list[AnomalyEvent] = Field(default_factory=list)


class POISearch(BaseModel):
    name: str = Field(max_length=64)
    images: Optional[List[str]] = None
    research: bool = False

    @field_validator("name")
    def validate_name(cls, value):
        return validate_non_empty_string(value, "name")

    @field_validator("images", mode="before")
    def validate_images(cls, value):
        if value is None:
            return value
        if not isinstance(value, list):
            raise ValueError("images must be a list")
        cleaned = []
        for image in value:
            cleaned.append(validate_non_empty_string(str(image), "image"))
        return cleaned

    @model_validator(mode="after")
    def validate_research_mode(self):
        if not self.research and not self.images:
            raise ValueError("images are required when research is false")
        return self


class Status(BaseModel):
    status: str
    frame_id: int | None = None
    total_frames: int | None = None
    module_status: dict[str, str] | None = None
    error_modules: list[str] | None = None
    run_id: str | None = None
    sources: list[InputSource] | None = None
    resources: ResourceSnapshot | None = None
    admission: AdmissionStatus | None = None
