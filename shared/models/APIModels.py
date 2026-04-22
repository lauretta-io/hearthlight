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
MODEL_BINDING_STAGES = {"detector", "tracker", "reid", "anomaly"}


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
    anomaly_model_key: str | None = None
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
    stage: str
    adapter: str
    artifact_ref: str | None = None
    runtime: dict = Field(default_factory=dict)
    capabilities: dict = Field(default_factory=dict)
    healthcheck: dict = Field(default_factory=dict)
    requires_gpu: bool = False
    resource_profile: dict = Field(default_factory=dict)
    source_path: str | None = None


class ModelBinding(BaseModel):
    stage: str
    model_key: str | None = None
    source_id: int | None = None
    binding_scope: str = "default"

    @field_validator("stage")
    def validate_stage(cls, value):
        normalized = validate_non_empty_string(value, "stage").lower()
        if normalized not in MODEL_BINDING_STAGES:
            raise ValueError("stage must be one of detector, tracker, reid, anomaly")
        return normalized


class ModelHealth(BaseModel):
    model_key: str
    stage: str
    adapter: str
    healthy: bool
    detail: str | None = None
    requires_gpu: bool = False


class ExportSink(BaseModel):
    sink_key: str
    adapter: str
    enabled: bool
    bootstrap_servers: list[str] = Field(default_factory=list)
    topics: dict = Field(default_factory=dict)
    batch: dict = Field(default_factory=dict)
    health: DependencyHealth | None = None


class ExporterStatus(BaseModel):
    sink_key: str | None = None
    enabled: bool = False
    healthy: bool = True
    detail: str | None = None
    last_flush_at: str | None = None
    queued_records: int = 0


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
    frame_id: int | None = None
    event_time: str | None = None
    title: str | None = None
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
    exporter_key: str
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
    exporter_status: ExporterStatus | None = None
    admission: AdmissionStatus | None = None
    drift: ResourceDrift | None = None
    updated_at: str | None = None


class UploadResponse(BaseModel):
    upload: UploadedMedia


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
    export_sinks: list[ExportSink] = Field(default_factory=list)
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
    exporter_status: ExporterStatus | None = None
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
