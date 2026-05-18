from typing import List
try:
    from typing_extensions import Self
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ fallback
    from typing import Self
from datetime import datetime
import uuid

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    field_serializer,
    model_validator,
    model_serializer,
)
from omegaconf import OmegaConf, DictConfig
import numpy as np
try:
    import torch
    _torch_available = True
except ImportError:
    torch = None
    _torch_available = False

from ..constants import VIDEO_EXTENSIONS


def to_ndarray_float32(x):
    if _torch_available and isinstance(x, torch.Tensor):
        return x.detach().cpu().numpy().astype(np.float32)
    if isinstance(x, list):
        return np.array(x, dtype=np.float32)
    return x


def to_ndarray_int32(x):
    return np.array(x, dtype=np.int32) if isinstance(x, list) else x


def to_ndarray_uint8(x):
    return np.array(x, dtype=np.uint8) if isinstance(x, list) else x


def to_list(x):
    if isinstance(x, np.ndarray):
        return x.tolist()
    if torch is not None and isinstance(x, torch.Tensor):
        return x.tolist()
    return x


class SystemCommand:
    START = "start"
    STOP = "stop"
    EXIT = "exit"


class SystemMessage(BaseModel, arbitrary_types_allowed=True):
    command: str
    config: DictConfig | None = None
    target_modules: list[str] | None = None

    @field_validator("config", mode="before")
    def validate_config(value):
        """
        json converts int keys to strings, so we need to convert them back
        """
        if value is None:
            return value

        def try_int(key):
            try:
                return int(key)
            except (TypeError, ValueError):
                return key

        def convert_key_to_int(dict_or_list):
            if isinstance(dict_or_list, dict):
                return {
                    try_int(k): convert_key_to_int(v) for k, v in dict_or_list.items()
                }
            elif isinstance(dict_or_list, list):
                return [convert_key_to_int(v) for v in dict_or_list]
            return dict_or_list

        value = convert_key_to_int(value)
        return OmegaConf.create(value)

    @field_serializer("config", when_used="json")
    def serialize_config(value):
        if value is None or isinstance(value, dict):
            return value
        return OmegaConf.to_container(value, resolve=True)


class Status:
    IDLE = "idle"
    INITIALIZED = "initialized"
    RUNNING = "running"
    ERROR = "error"
    STOPPED = "stopped"
    EXIT = "exit"
    INFO = "info"


class StatusMessage(BaseModel):
    status: str
    module: str
    extra: dict | None = None


class AssetReference(BaseModel):
    uri: str
    media_type: str
    checksum_sha256: str | None = None
    size_bytes: int | None = None
    producer: str | None = None
    timestamp: str | None = None


class TrackInstance(BaseModel, arbitrary_types_allowed=True):
    id: int = uuid.uuid4().int
    real_id: int | None = None
    track_id: int
    bbox: list[float]
    cam_id: int
    clss: str
    confidence: float | None = None
    timestamp: float
    frame_id: int
    confirmed: bool = False
    feature: np.ndarray | None = None
    feature_id: int | None = None
    keypoints: np.ndarray | None = None
    body_visible: bool | None = None
    face_visible: bool | None = None
    zone_id: int | None = None

    _np_int = field_validator("bbox", mode="before")(to_ndarray_int32)
    _torch_float = field_validator("feature", "keypoints", mode="before")(
        to_ndarray_float32
    )
    _list = field_serializer("bbox", "feature", "keypoints", when_used="json")(to_list)

    def drop_tensors(self):
        self.feature = None
        self.keypoints = None


class TrackInstances(BaseModel):
    frame_id: int
    track_instances: List[TrackInstance]


class IdentifiedTrackInstances(BaseModel):
    frame_id: int
    track_instances: List[TrackInstance]
    id_updates: dict[int, int]
    id_guesses: dict[int, int]


class Detection(BaseModel, arbitrary_types_allowed=True):
    bbox: np.ndarray
    cam_id: int
    clss: str
    confidence: float | None = None

    _np_int = field_validator("bbox", mode="before")(to_ndarray_int32)
    _list = field_serializer("bbox", when_used="json")(to_list)


class Detections(BaseModel):
    frame_id: int
    detections: List[Detection]


class FrameInfo(BaseModel):
    """
    used downstream to store metadata from a Frame instance without the array or dets
    """

    cam_id: int
    timestamp: float
    time_delta: float
    status: bool = True
    empty: bool = True
    save_path: str | None = None


class Frame(BaseModel, arbitrary_types_allowed=True):
    cam_id: int
    timestamp: float
    time_delta: float
    array: np.ndarray
    resized_array: np.ndarray | None = None
    status: bool = True
    empty: bool = True
    save_path: str | None = None
    tracks: List[TrackInstance] = Field(default_factory=list)
    tracker_inputs: np.ndarray | None = None
    detections: List[Detection] = Field(default_factory=list)

    _np_uint8 = field_validator("array", mode="before")(to_ndarray_uint8)

    @model_serializer
    def seralize_model(self):
        return {
            "cam_id": self.cam_id,
            "timestamp": self.timestamp,
            "time_delta": self.time_delta,
            "status": self.status,
            "empty": self.empty,
            "save_path": self.save_path,
        }


class Frames(BaseModel):
    frame_id: int
    frames: List[Frame | FrameInfo]

    def get_frame(self, cam_id: int) -> Frame | FrameInfo:
        for frame in self.frames:
            if frame.cam_id == cam_id:
                return frame
        raise ValueError(f"Frame with cam_id {cam_id} not found")

    def get_frames(self, cam_ids: List[int]) -> List[Frame | FrameInfo]:
        return [frame for frame in self.frames if frame.cam_id in cam_ids]


class JourneyNode(BaseModel):
    track_instance: TrackInstance
    start_timestamp: float
    stop_timestamp: float
    cam_id: int
    zone_id: int | None = None


class POIResult(BaseModel):
    search_id: int
    ids: List[int]


class POISearch(BaseModel, arbitrary_types_allowed=True):
    search_id: int
    feature: np.ndarray | None = None

    _numpy_float = field_validator("feature", mode="before")(to_ndarray_float32)
    _list = field_serializer("feature", when_used="json")(to_list)


# temporary hack


class ResolutionMessage(BaseModel):
    incident_id: int
    status: str | None = None


class AnomalyEvent(BaseModel):
    event_id: str
    run_id: str | None = None
    source_id: int | None = None
    camera_id: int | None = None
    frame_id: int | None = None
    stage_1_model_key: str | None = None
    stage_2_model_key: str | None = None
    title: str | None = None
    model_key: str
    category: str
    score: float
    reasoning: str | None = None
    visible_items: list[str] = Field(default_factory=list)
    visible_activities: list[str] = Field(default_factory=list)
    asset_references: list[AssetReference] = Field(default_factory=list)


class AnomalyEvents(BaseModel):
    frame_id: int
    events: list[AnomalyEvent]


class CameraType:
    CAMERA = "camera"
    VIDEO_FILE = "video_file"
    WEBCAM = "webcam"


class Camera(BaseModel):
    cam_id: int
    tasks: List[str]
    source: str | int
    name: str | None = None
    camera_type: str | None = None
    start_timestamp: float | None = None
    start_datetime: str | None = None
    run_id: int | None = None
    recording_path: str | None = None
    x_loc: float | int | None = None
    y_loc: float | int | None = None
    width: int | None = None
    height: int | None = None
    total_frames: int | None = None
    source_template_id: int | None = None
    upload_id: int | None = None
    process_every_n_frames: int = 1
    detector_model_key: str | None = None
    tracker_model_key: str | None = None
    reid_model_key: str | None = None
    anomaly_stage_1_model_key: str | None = None
    anomaly_stage_2_model_key: str | None = None

    @model_validator(mode="after")
    def set_type(self) -> Self:
        if isinstance(self.source, int):
            self.camera_type = CameraType.WEBCAM
        elif self.source.split(".")[-1] in VIDEO_EXTENSIONS:
            self.camera_type = CameraType.VIDEO_FILE
        else:
            self.camera_type = CameraType.CAMERA
        if self.start_timestamp is not None:
            self.start_datetime = datetime.fromtimestamp(
                self.start_timestamp
            ).isoformat()
        if self.tasks:
            self.tasks = [task.upper() for task in self.tasks]

        return self

    def set_start_timestamp(self, timestamp: float):
        self.start_timestamp = timestamp
        self.start_datetime = datetime.fromtimestamp(self.start_timestamp).isoformat()


class Run(BaseModel):
    run_identifier: str
    output_dir: str
    cameras: List[Camera]
    run_id: int | None = None
    start_timestamp: float | None = None
    start_datetime: str | None = None

    @model_validator(mode="after")
    def set_times(self) -> Self:
        timestamps = [
            cam.start_timestamp
            for cam in self.cameras
            if cam.start_timestamp is not None
        ]
        if timestamps:
            self.start_timestamp = min(timestamps)
            self.start_datetime = datetime.fromtimestamp(
                self.start_timestamp
            ).isoformat()
        return self
