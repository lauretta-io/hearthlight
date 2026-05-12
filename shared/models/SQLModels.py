from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    text,
    UniqueConstraint,
)
from sqlalchemy.orm import mapped_column
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import ARRAY


Base = declarative_base()
metadata = Base.metadata


class Run(Base):
    __tablename__ = "run"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_identifier = mapped_column(Text, primary_key=True)
    output_dir = mapped_column(Text, primary_key=True)
    start_timestamp = mapped_column(Float)
    start_datetime = mapped_column(DateTime)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False)
    deleted_at = mapped_column(DateTime)


class Camera(Base):
    __tablename__ = "camera"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    name = mapped_column(String(255))
    tasks = mapped_column(ARRAY(String))
    cam_model_id = mapped_column(Integer)
    cam_ip_address = mapped_column(String(255))
    description = mapped_column(String(255))
    moving = mapped_column(Integer)
    camera_height = mapped_column(Integer)
    connection_type = mapped_column(String(255))
    controllable = mapped_column(Integer)
    pan_left = mapped_column(Integer)
    pan_right = mapped_column(Integer)
    tilt_up = mapped_column(Integer)
    tilt_down = mapped_column(Integer)
    zoom_in = mapped_column(Integer)
    zoom_out = mapped_column(Integer)
    camera_loc_x = mapped_column(Float)
    camera_loc_y = mapped_column(Float)
    camera_cov_x1 = mapped_column(Float)
    camera_cov_y1 = mapped_column(Float)
    camera_cov_x2 = mapped_column(Float)
    camera_cov_y2 = mapped_column(Float)
    camera_cov_points = mapped_column(String(1000))
    rotation = mapped_column(Float)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False)
    deleted_at = mapped_column(DateTime)


class CameraRecording(Base):
    __tablename__ = "camera_recording"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    cam_id = mapped_column(Integer)
    run_id = mapped_column(Integer)
    width = mapped_column(Integer)
    height = mapped_column(Integer)
    cam_recording_path = mapped_column(Text)
    source_kind = mapped_column(String(32))
    source_template_id = mapped_column(Integer)
    upload_id = mapped_column(Integer)
    total_frames = mapped_column(Integer)
    constant_frame_rate = mapped_column(Boolean)
    start_timestamp = mapped_column(Float)
    start_datetime = mapped_column(DateTime)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False)
    deleted_at = mapped_column(DateTime)


class CameraModel(Base):
    __tablename__ = "camera_model"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    camera_id = mapped_column(Integer)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False)
    deleted_at = mapped_column(DateTime)


class CameraZoneMapping(Base):
    __tablename__ = "camera_zone_mapping"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    cam_id = mapped_column(Integer, nullable=False)
    zone_id = mapped_column(Integer, nullable=False)
    zone_x1 = mapped_column(Float)
    zone_y1 = mapped_column(Float)
    zone_x2 = mapped_column(Float)
    zone_y2 = mapped_column(Float)
    cam_view_x1 = mapped_column(Float)
    cam_view_y1 = mapped_column(Float)
    cam_view_x2 = mapped_column(Float)
    cam_view_y2 = mapped_column(Float)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False)
    deleted_at = mapped_column(DateTime)


class Bag(Base):
    __tablename__ = "bag"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id = mapped_column(Integer, nullable=False)
    large_ = mapped_column(Boolean)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False)
    deleted_at = mapped_column(DateTime)


class BagInstance(Base):
    __tablename__ = "bag_instance"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id = mapped_column(Integer, nullable=False)
    bag_id = mapped_column(Integer)
    track_id = mapped_column(Integer, nullable=False)
    cam_id = mapped_column(Integer)
    zone_id = mapped_column(String(255))
    bbox = mapped_column(ARRAY(Float))
    datetime = mapped_column(DateTime)
    timestamp = mapped_column(Float)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean)
    deleted_at = mapped_column(DateTime)


class BagJourneyMapping(Base):
    __tablename__ = "bag_journey_mapping"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    bag_id = mapped_column(Integer)
    journey_node_id = mapped_column(Integer)
    is_deleted = mapped_column(Boolean)
    deleted_at = mapped_column(DateTime)
    created_at = mapped_column(DateTime)
    updated_at = mapped_column(DateTime)


class Frame(Base):
    __tablename__ = "frame"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id = mapped_column(Integer)
    path = mapped_column(Text)
    cam_id = mapped_column(Integer)
    frame_id = mapped_column(Integer)
    timestamp = mapped_column(Float)
    datetime = mapped_column(DateTime)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False)
    deleted_at = mapped_column(DateTime)


class Incident(Base):
    __tablename__ = "incident"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id = mapped_column(Integer, nullable=False)
    incident_type = mapped_column(String(255))
    status = mapped_column(String(255))
    camera_id = mapped_column(Integer)
    zone_id = mapped_column(Integer)
    timestamp = mapped_column(Float)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    current_update = mapped_column(Integer)
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_by = mapped_column(String(255))
    is_deleted = mapped_column(Boolean)
    deleted_at = mapped_column(DateTime)


class IncidentBagMapping(Base):
    __tablename__ = "incident_bag_mapping"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id = mapped_column(Integer, nullable=False)
    bag_id = mapped_column(Integer, nullable=False)
    role = mapped_column(String(255))
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean)
    deleted_at = mapped_column(DateTime)


class IncidentPersonMapping(Base):
    __tablename__ = "incident_person_mapping"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id = mapped_column(Integer, nullable=False)
    person_id = mapped_column(Integer, nullable=False)
    role = mapped_column(String(255))
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean)
    deleted_at = mapped_column(DateTime)


class IncidentUpdate(Base):
    __tablename__ = "incident_update"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id = mapped_column(Integer, nullable=False)
    incident_id = mapped_column(Integer, nullable=False)
    new_status = mapped_column(String(255))
    old_status = mapped_column(String(255))
    updated_by = mapped_column(String(255))
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class JourneyNode(Base):
    __tablename__ = "journey_node"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id = mapped_column(Integer, nullable=False)
    camera_id = mapped_column(Integer)
    zone_id = mapped_column(Integer)
    start_timestamp = mapped_column(Float)
    stop_timestamp = mapped_column(Float)
    crop_bbox = mapped_column(ARRAY(Float))
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    deleted_at = mapped_column(DateTime)
    is_deleted = mapped_column(Boolean)


class Person(Base):
    __tablename__ = "person"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id = mapped_column(Integer, nullable=False)
    threat_status = mapped_column(Boolean, default=False)
    name = mapped_column(String(255))
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False)
    deleted_at = mapped_column(DateTime)


class EntityIdMapping(Base):
    __tablename__ = "entity_id_mapping"
    __table_args__ = (
        UniqueConstraint(
            "temporary_id", "entity_type", name="uq_temp_id_per_entity_type"
        ),
        {"schema": "dicos"},
    )

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    persistent_id = mapped_column(Integer, nullable=False, index=True)
    temporary_id = mapped_column(Integer, nullable=False, index=True)
    entity_type = mapped_column(String(50), nullable=False)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class PersonBagMapping(Base):
    __tablename__ = "person_bag_mapping"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id = mapped_column(Integer)
    bag_id = mapped_column(Integer)
    distance = mapped_column(Float)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False)
    deleted_at = mapped_column(DateTime)


class PersonInstance(Base):
    __tablename__ = "person_instance"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id = mapped_column(Integer, nullable=False)
    person_id = mapped_column(Integer)
    track_id = mapped_column(Integer, nullable=False)
    cam_id = mapped_column(Integer)
    zone_id = mapped_column(String(255))
    bbox = mapped_column(ARRAY(Float))
    timestamp = mapped_column(Float)
    datetime = mapped_column(DateTime)
    frame_id = mapped_column(Integer)
    feature_id = mapped_column(Integer)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean)
    deleted_at = mapped_column(DateTime)


class PersonJourneyMapping(Base):
    __tablename__ = "person_journey_mapping"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id = mapped_column(Integer)
    journey_node_id = mapped_column(Integer)
    is_deleted = mapped_column(Boolean)
    deleted_at = mapped_column(DateTime)
    created_at = mapped_column(DateTime)
    updated_at = mapped_column(DateTime)


class POISearch(Base):
    __tablename__ = "poi_search"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id = mapped_column(Integer)
    name = mapped_column(String(255))
    crop_dir = mapped_column(Text)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False)
    deleted_at = mapped_column(DateTime)


class POIResultMapping(Base):
    __tablename__ = "poi_result_mapping"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    search_id = mapped_column(Integer)
    result_id = mapped_column(Integer)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False)
    deleted_at = mapped_column(DateTime)


class POISearchResult(Base):
    __tablename__ = "poi_search_result"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id = mapped_column(Integer)
    person_ids = mapped_column(ARRAY(Integer))
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False)
    deleted_at = mapped_column(DateTime)


class Zone(Base):
    __tablename__ = "zone"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    name_ = mapped_column(String(255))
    description = mapped_column(String(255))
    floor_level = mapped_column(String(10))
    camera_id = mapped_column(Integer)
    points = mapped_column(ARRAY(Float))
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False)
    deleted_at = mapped_column(DateTime)


class InputSourceTemplate(Base):
    __tablename__ = "input_source_template"
    __table_args__ = {"schema": "control"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind = mapped_column(String(32), nullable=False)
    label = mapped_column(String(255), nullable=False)
    source_value = mapped_column(Text)
    upload_id = mapped_column(Integer)
    tasks = mapped_column(ARRAY(String), nullable=False)
    enabled = mapped_column(Boolean, default=True, nullable=False)
    sort_order = mapped_column(Integer, default=0, nullable=False)
    last_error = mapped_column(Text)
    detector_model_key = mapped_column(String(128))
    tracker_model_key = mapped_column(String(128))
    reid_model_key = mapped_column(String(128))
    anomaly_stage_1_model_key = mapped_column(String(128))
    anomaly_stage_2_model_key = mapped_column(String(128))
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False, nullable=False)
    deleted_at = mapped_column(DateTime)


class UploadedMedia(Base):
    __tablename__ = "uploaded_media"
    __table_args__ = {"schema": "control"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    original_filename = mapped_column(String(255), nullable=False)
    stored_path = mapped_column(Text, nullable=False)
    checksum_sha256 = mapped_column(String(64), nullable=False)
    size_bytes = mapped_column(Integer, nullable=False)
    lifecycle_state = mapped_column(String(32), nullable=False)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False, nullable=False)
    deleted_at = mapped_column(DateTime)


class ResourceSnapshot(Base):
    __tablename__ = "resource_snapshot"
    __table_args__ = {"schema": "control"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    cpu_percent = mapped_column(Float)
    memory_percent = mapped_column(Float)
    disk_percent = mapped_column(Float)
    gpu_json = mapped_column(Text)
    module_status_json = mapped_column(Text)
    model_health_json = mapped_column(Text)
    admission_json = mapped_column(Text)
    drift_json = mapped_column(Text)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class ResourceEvent(Base):
    __tablename__ = "resource_event"
    __table_args__ = {"schema": "control"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type = mapped_column(String(64), nullable=False)
    severity = mapped_column(String(32), nullable=False)
    message = mapped_column(Text, nullable=False)
    metadata_json = mapped_column(Text)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class ModelRegistration(Base):
    __tablename__ = "model_registration"
    __table_args__ = {"schema": "control"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_key = mapped_column(String(128), nullable=False)
    stage = mapped_column(String(32), nullable=False)
    adapter = mapped_column(String(128), nullable=False)
    artifact_ref = mapped_column(Text)
    runtime_json = mapped_column(Text)
    capability_json = mapped_column(Text)
    healthcheck_json = mapped_column(Text)
    requires_gpu = mapped_column(Boolean, default=False, nullable=False)
    resource_profile_json = mapped_column(Text)
    source_path = mapped_column(Text)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False, nullable=False)
    deleted_at = mapped_column(DateTime)


class ModelBindingTemplate(Base):
    __tablename__ = "model_binding_template"
    __table_args__ = {"schema": "control"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    stage = mapped_column(String(32), nullable=False)
    binding_scope = mapped_column(String(32), nullable=False)
    source_template_id = mapped_column(Integer)
    model_key = mapped_column(String(128))
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False, nullable=False)
    deleted_at = mapped_column(DateTime)


class AlertRuleTemplate(Base):
    __tablename__ = "alert_rule_template"
    __table_args__ = {"schema": "control"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_template_id = mapped_column(Integer, nullable=False)
    enabled = mapped_column(Boolean, default=True, nullable=False)
    sort_order = mapped_column(Integer, default=0, nullable=False)
    rule_label = mapped_column(String(255))
    signal_family = mapped_column(String(32), nullable=False)
    target_key = mapped_column(String(255), nullable=False)
    min_confidence = mapped_column(Float, default=0.5, nullable=False)
    alert_level = mapped_column(String(16), default="medium", nullable=False)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False, nullable=False)
    deleted_at = mapped_column(DateTime)


class TelegramTriggerSubscription(Base):
    __tablename__ = "telegram_trigger_subscription"
    __table_args__ = {"schema": "control"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    enabled = mapped_column(Boolean, default=True, nullable=False)
    subscription_label = mapped_column(String(255))
    bot_token = mapped_column(Text, nullable=False)
    chat_id = mapped_column(String(255), nullable=False)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False, nullable=False)
    deleted_at = mapped_column(DateTime)


class AppleMessageTriggerSubscription(Base):
    __tablename__ = "apple_message_trigger_subscription"
    __table_args__ = {"schema": "control"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    enabled = mapped_column(Boolean, default=True, nullable=False)
    subscription_label = mapped_column(String(255))
    recipient_handle = mapped_column(String(255), nullable=False)
    service = mapped_column(String(32), nullable=False, default="iMessage")
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False, nullable=False)
    deleted_at = mapped_column(DateTime)


class AnomalyEvent(Base):
    __tablename__ = "anomaly_event"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id = mapped_column(Integer, nullable=False)
    source_template_id = mapped_column(Integer)
    camera_id = mapped_column(Integer)
    frame_id = mapped_column(Integer)
    event_key = mapped_column(String(128), nullable=False)
    model_key = mapped_column(String(128), nullable=False)
    stage_1_model_key = mapped_column(String(128))
    stage_2_model_key = mapped_column(String(128))
    category = mapped_column(String(128), nullable=False)
    title = mapped_column(Text)
    score = mapped_column(Float, nullable=False)
    reasoning = mapped_column(Text)
    visible_items_json = mapped_column(Text)
    visible_activities_json = mapped_column(Text)
    asset_refs_json = mapped_column(Text)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False, nullable=False)
    deleted_at = mapped_column(DateTime)


class AlertIncident(Base):
    __tablename__ = "alert_incident"
    __table_args__ = {"schema": "dicos"}

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id = mapped_column(Integer, nullable=False)
    incident_id = mapped_column(Integer, nullable=False)
    alert_rule_id = mapped_column(Integer, nullable=False)
    source_template_id = mapped_column(Integer)
    signal_family = mapped_column(String(32), nullable=False)
    matched_target = mapped_column(String(255), nullable=False)
    confidence = mapped_column(Float, nullable=False)
    alert_level = mapped_column(String(16), nullable=False)
    title = mapped_column(Text, nullable=False)
    model_keys_json = mapped_column(Text)
    dedupe_key = mapped_column(String(255), nullable=False)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False, nullable=False)
    deleted_at = mapped_column(DateTime)
    created_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    is_deleted = mapped_column(Boolean, default=False, nullable=False)
    deleted_at = mapped_column(DateTime)
