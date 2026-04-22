from __future__ import annotations

import logging
from hashlib import sha256
from pathlib import Path
from typing import Iterable
from uuid import uuid4

try:
    import cv2
except ImportError:  # pragma: no cover - optional local dependency
    cv2 = None

from .security import sanitize_identifier

SOURCE_KIND_CAMERA_URL = "camera_url"
SOURCE_KIND_VIDEO_UPLOAD = "video_upload"
SOURCE_KIND_WEBCAM = "webcam"
UPLOAD_STATE_STAGED = "staged"
UPLOAD_STATE_ATTACHED = "attached"
UPLOAD_STATE_ACTIVE = "active"
UPLOAD_STATE_DELETED = "deleted"
DEFAULT_SOURCE_PROBE_TIMEOUT_MS = 5000

logger = logging.getLogger(__name__)


def build_upload_filename(original_filename: str) -> str:
    original_path = Path(original_filename)
    stem = sanitize_identifier(original_path.stem or "upload", fallback="upload")
    suffix = original_path.suffix.lower()
    return f"{stem}_{uuid4().hex}{suffix}"


def compute_sha256(file_path: str | Path) -> str:
    digest = sha256()
    with Path(file_path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def coerce_source_value(kind: str, source_value: str | int | None, upload_path: str | None = None):
    if kind == SOURCE_KIND_VIDEO_UPLOAD:
        if not upload_path:
            raise ValueError("upload_path is required for video upload sources")
        return upload_path
    if kind == SOURCE_KIND_WEBCAM:
        if source_value is None:
            raise ValueError("source_value is required for webcam sources")
        return int(source_value)
    if source_value is None:
        raise ValueError("source_value is required for camera sources")
    return source_value


def build_runtime_camera_entry(
    source_row,
    *,
    upload_path: str | None = None,
) -> dict:
    return {
        "name": source_row.label,
        "tasks": list(source_row.tasks),
        "source": coerce_source_value(source_row.kind, source_row.source_value, upload_path),
        "source_template_id": source_row.id,
        "upload_id": source_row.upload_id,
        "detector_model_key": getattr(source_row, "detector_model_key", None),
        "tracker_model_key": getattr(source_row, "tracker_model_key", None),
        "reid_model_key": getattr(source_row, "reid_model_key", None),
        "anomaly_model_key": getattr(source_row, "anomaly_model_key", None),
    }


def build_runtime_camera_map(
    source_rows: Iterable,
    upload_paths: dict[int, str],
) -> dict[int, dict]:
    camera_map = {}
    for order, source_row in enumerate(source_rows):
        camera_map[order] = build_runtime_camera_entry(
            source_row,
            upload_path=upload_paths.get(source_row.upload_id),
        )
    return camera_map


def source_requires_gpu(source_rows: Iterable) -> bool:
    return any(getattr(source_row, "enabled", True) for source_row in source_rows)


def derive_upload_lifecycle_state(
    *,
    is_deleted: bool,
    is_attached: bool,
    is_enabled: bool,
) -> str:
    if is_deleted:
        return UPLOAD_STATE_DELETED
    if is_enabled:
        return UPLOAD_STATE_ACTIVE
    if is_attached:
        return UPLOAD_STATE_ATTACHED
    return UPLOAD_STATE_STAGED


def derive_source_error(
    *,
    kind: str,
    enabled: bool,
    upload_id: int | None = None,
    upload_path: str | None = None,
    upload_exists: bool = True,
    upload_lifecycle_state: str | None = None,
) -> str | None:
    if kind != SOURCE_KIND_VIDEO_UPLOAD or not enabled:
        return None
    if upload_id is None:
        return "upload reference is missing"
    if upload_lifecycle_state == UPLOAD_STATE_DELETED:
        return "uploaded media has been deleted"
    if not upload_path:
        return "uploaded media metadata is missing"
    if not upload_exists:
        return "uploaded media file is missing on disk"
    return None


def configure_capture_timeouts(capture, timeout_ms: int):
    if cv2 is None:
        return
    for property_name in ("CAP_PROP_OPEN_TIMEOUT_MSEC", "CAP_PROP_READ_TIMEOUT_MSEC"):
        property_id = getattr(cv2, property_name, None)
        if property_id is None:
            continue
        try:
            capture.set(property_id, timeout_ms)
        except Exception:
            logger.debug("OpenCV capture timeout %s is unsupported", property_name)


def open_capture(capture, source) -> bool:
    try:
        if cv2 is None:
            return bool(capture.open(source))
        return bool(capture.open(source, cv2.CAP_ANY))
    except TypeError:
        return bool(capture.open(source))


def probe_source_connection(
    kind: str,
    source_value: str | int | None,
    *,
    upload_path: str | None = None,
    capture_factory=None,
    timeout_ms: int = DEFAULT_SOURCE_PROBE_TIMEOUT_MS,
) -> str | None:
    resolved_source = coerce_source_value(kind, source_value, upload_path)
    if kind == SOURCE_KIND_VIDEO_UPLOAD and not Path(str(resolved_source)).exists():
        return "uploaded media file is missing on disk"
    if capture_factory is None and cv2 is None:
        return "opencv capture backend is unavailable"

    capture = capture_factory() if capture_factory is not None else cv2.VideoCapture()
    try:
        configure_capture_timeouts(capture, timeout_ms)
        opened = open_capture(capture, resolved_source)
        is_opened = capture.isOpened() if hasattr(capture, "isOpened") else opened
        if not opened or not is_opened:
            return "source could not be opened"
        # For network streams, frame decode can fail due to codec quirks (e.g. non-conformant
        # HEVC parameter sets) even when the source is fully reachable.  A successful open
        # with valid dimensions from the SDP is sufficient proof of connectivity.
        if kind == SOURCE_KIND_CAMERA_URL and cv2 is not None and hasattr(capture, "get"):
            width = capture.get(cv2.CAP_PROP_FRAME_WIDTH)
            height = capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
            if width > 0 and height > 0:
                return None
        received_frame, _ = capture.read()
        if not received_frame:
            return "source opened but did not yield a frame"
        return None
    except Exception:
        logger.exception("Failed to probe source connection")
        return "source validation failed"
    finally:
        if hasattr(capture, "release"):
            capture.release()
