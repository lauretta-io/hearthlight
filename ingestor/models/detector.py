import logging
import shutil
import subprocess

import numpy as np
try:
    import cv2
except ModuleNotFoundError:  # pragma: no cover - optional local CPU fallback
    cv2 = None

from ...shared.models.DataModels import Detection
from ...shared.utils.config import get_tasks
from ...shared.utils.bbox import clip_coords
from ...shared.utils.model_registry import (
    MODEL_STAGE_DETECTOR,
    build_default_bindings,
    get_registration,
    load_registry_bundle,
)
from ...shared.constants import Tasks

logger = logging.getLogger(__name__)

# COCO class ids used by YOLOv8 when falling back from the stub model-zoo detector.
_YOLO_PERSON_CLASS_ID = 0
_YOLO_BAG_CLASS_IDS = {24, 26, 28}
_YOLO_NMS_IOU_THRESHOLD = 0.45


def _model_zoo_detector_is_stub(model) -> bool:
    probe = np.zeros((480, 640, 3), dtype=np.uint8)
    try:
        result = model([probe], {0: 0.01, 1: 0.01})
    except Exception:
        return False
    if not result:
        return True
    output = np.asarray(result[0])
    return output.size == 0


def _nms_numpy(boxes, scores, iou_threshold=_YOLO_NMS_IOU_THRESHOLD):
    if len(boxes) == 0:
        return np.empty((0,), dtype=np.int64)

    boxes = np.asarray(boxes, dtype=np.float32)
    scores = np.asarray(scores, dtype=np.float32)
    x1, y1, x2, y2 = boxes.T
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep = []

    while order.size:
        current = order[0]
        keep.append(current)
        if order.size == 1:
            break

        remaining = order[1:]
        xx1 = np.maximum(x1[current], x1[remaining])
        yy1 = np.maximum(y1[current], y1[remaining])
        xx2 = np.minimum(x2[current], x2[remaining])
        yy2 = np.minimum(y2[current], y2[remaining])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        union = areas[current] + areas[remaining] - inter
        iou = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)
        order = remaining[iou <= iou_threshold]

    return np.asarray(keep, dtype=np.int64)


def _normalize_yolo_prediction(prediction):
    prediction = np.asarray(prediction, dtype=np.float32)
    if prediction.ndim == 3:
        prediction = prediction[0]
    if prediction.ndim != 2 or prediction.size == 0:
        return np.zeros((0, 0), dtype=np.float32)
    if 5 <= prediction.shape[0] <= 128 and prediction.shape[1] > 128:
        prediction = prediction.T
    return prediction


def _filter_yolo_prediction_rows(
    prediction,
    frame_shape,
    model_size,
    person_threshold,
    bag_threshold,
):
    prediction = _normalize_yolo_prediction(prediction)
    if prediction.shape[1] <= 4:
        return np.zeros((0, 6), dtype=np.float32)

    frame_h, frame_w = frame_shape[:2]
    scale_x = frame_w / float(model_size)
    scale_y = frame_h / float(model_size)
    rows = []

    for item in prediction:
        cx, cy, width, height = item[:4]
        class_scores = item[4:]
        if class_scores.size <= _YOLO_PERSON_CLASS_ID:
            continue

        candidates = [(_YOLO_PERSON_CLASS_ID, 0, person_threshold)]
        candidates.extend((class_id, 1, bag_threshold) for class_id in _YOLO_BAG_CLASS_IDS)
        for coco_class_id, hearthlight_class_id, threshold in candidates:
            if coco_class_id >= class_scores.size:
                continue
            confidence = float(class_scores[coco_class_id])
            if confidence < threshold:
                continue
            x1 = max(0.0, (cx - width / 2.0) * scale_x)
            y1 = max(0.0, (cy - height / 2.0) * scale_y)
            x2 = min(float(frame_w), (cx + width / 2.0) * scale_x)
            y2 = min(float(frame_h), (cy + height / 2.0) * scale_y)
            if x2 <= x1 or y2 <= y1:
                continue
            rows.append([x1, y1, x2, y2, confidence, hearthlight_class_id])

    if not rows:
        return np.zeros((0, 6), dtype=np.float32)

    detections = np.asarray(rows, dtype=np.float32)
    keep_indices = []
    for class_id in (0, 1):
        class_indices = np.flatnonzero(detections[:, 5] == class_id)
        keep = _nms_numpy(
            detections[class_indices, :4],
            detections[class_indices, 4],
            _YOLO_NMS_IOU_THRESHOLD,
        )
        keep_indices.extend(class_indices[keep].tolist())
    if not keep_indices:
        return np.zeros((0, 6), dtype=np.float32)
    return detections[np.asarray(keep_indices, dtype=np.int64)]


class RTDetrDetectorAdapter:
    def __init__(self, cfg, registration):
        from hearthlight_model_zoo.detectors import Detector as OD

        runtime = registration.get("runtime") or {}
        self.names = cfg.rtdetr.names
        self.conf_thresh = cfg.rtdetr.conf_thresh
        tasks = get_tasks(cfg)
        classes = {i: clss for i, clss in cfg.rtdetr.names.items() if clss.upper() in tasks}
        self.conf_dict = {i: self.conf_thresh[classes[i]] for i in classes}
        self.track_class_ids = set(cfg.tracking.classes.keys())
        self.model = OD(
            registration.get("artifact_ref") or cfg.rtdetr.model_name,
            runtime.get("backend", "trt"),
            runtime.get("precision", "fp16"),
            device=runtime.get("device", "cuda:0"),
        )
        self._ultralytics_model = None
        self._hog_descriptor = None
        if _model_zoo_detector_is_stub(self.model):
            try:
                from ultralytics import YOLO
            except ImportError as exc:
                logger.warning(
                    "hearthlight_model_zoo detector is a compatibility stub and ultralytics is unavailable; "
                    "falling back to OpenCV HOG person detection",
                )
                self._init_hog_fallback()
            else:
                logger.warning(
                    "hearthlight_model_zoo detector is a compatibility stub; "
                    "using ultralytics YOLOv8n fallback for local detection",
                )
                self._ultralytics_model = YOLO("yolov8n.pt")
                configured_size = cfg.rtdetr.get("local_cpu_img_size", 640)
                try:
                    self._ultralytics_img_size = max(320, min(int(configured_size), 960))
                except (TypeError, ValueError):
                    self._ultralytics_img_size = 640
        configured_size = cfg.rtdetr.get("local_cpu_img_size", 640)
        try:
            self._hog_img_size = max(320, min(int(configured_size), 960))
        except (TypeError, ValueError):
            self._hog_img_size = 640

    def _init_hog_fallback(self):
        if cv2 is None:
            raise RuntimeError(
                "detector runtime unavailable: install ultralytics or opencv-python for local CPU fallback"
            )
        hog = cv2.HOGDescriptor()
        hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self._hog_descriptor = hog

    def _frame_array(self, frame):
        return frame.array if hasattr(frame, "array") else frame

    def _infer_ultralytics(self, frames):
        outputs = []
        person_threshold = float(self.conf_dict.get(0, 0.35))
        bag_threshold = float(self.conf_dict.get(1, 0.35))
        for frame in frames:
            outputs.append(
                self._infer_ultralytics_frame(
                    self._frame_array(frame),
                    person_threshold,
                    bag_threshold,
                )
            )
        return outputs

    def _infer_ultralytics_frame(self, frame, person_threshold, bag_threshold):
        try:
            return self._infer_ultralytics_direct(frame, person_threshold, bag_threshold)
        except Exception:
            logger.exception("Ultralytics CPU fallback failed; returning empty detections")
            return np.zeros((0, 6), dtype=np.float32)

    def _infer_hog(self, frames):
        outputs = []
        person_threshold = float(self.conf_dict.get(0, 0.35))
        for frame in frames:
            outputs.append(
                self._infer_hog_frame(
                    self._frame_array(frame),
                    person_threshold,
                )
            )
        return outputs

    def _infer_hog_frame(self, frame, person_threshold):
        try:
            return self._infer_hog_direct(frame, person_threshold)
        except Exception:
            logger.exception("OpenCV HOG fallback failed; returning empty detections")
            return np.zeros((0, 6), dtype=np.float32)

    def _infer_hog_direct(self, frame, person_threshold):
        if self._hog_descriptor is None:
            return np.zeros((0, 6), dtype=np.float32)
        frame_h, frame_w = frame.shape[:2]
        max_dim = max(frame_h, frame_w)
        scale = 1.0
        resized = frame
        if max_dim > self._hog_img_size:
            scale = self._hog_img_size / float(max_dim)
            resized = cv2.resize(
                frame,
                (max(1, int(frame_w * scale)), max(1, int(frame_h * scale))),
                interpolation=cv2.INTER_LINEAR,
            )
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        rects, weights = self._hog_descriptor.detectMultiScale(
            gray,
            winStride=(8, 8),
            padding=(8, 8),
            scale=1.05,
        )
        if len(rects) == 0:
            return np.zeros((0, 6), dtype=np.float32)

        rows = []
        for (x, y, w, h), weight in zip(rects, weights):
            confidence = float(weight) if weight is not None else 0.5
            if confidence < person_threshold:
                continue
            x1 = float(max(0.0, x / scale))
            y1 = float(max(0.0, y / scale))
            x2 = float(max(x1, (x + w) / scale))
            y2 = float(max(y1, (y + h) / scale))
            rows.append([x1, y1, x2, y2, confidence, 0.0])
        if not rows:
            return np.zeros((0, 6), dtype=np.float32)

        detections = np.asarray(rows, dtype=np.float32)
        keep = _nms_numpy(detections[:, :4], detections[:, 4], _YOLO_NMS_IOU_THRESHOLD)
        if keep.size == 0:
            return np.zeros((0, 6), dtype=np.float32)
        return detections[keep]

    def _infer_ultralytics_direct(self, frame, person_threshold, bag_threshold):
        # Use the public Ultralytics predictor path; direct internal model calls
        # can hang on some host/python/torch combinations in local CPU mode.
        results = self._ultralytics_model.predict(
            source=frame,
            imgsz=self._ultralytics_img_size,
            verbose=False,
            iou=_YOLO_NMS_IOU_THRESHOLD,
            device="cpu",
        )
        if not results:
            return np.zeros((0, 6), dtype=np.float32)

        boxes = results[0].boxes
        if boxes is None or boxes.xyxy is None or len(boxes.xyxy) == 0:
            return np.zeros((0, 6), dtype=np.float32)

        xyxy = boxes.xyxy.detach().cpu().numpy()
        conf = boxes.conf.detach().cpu().numpy()
        cls = boxes.cls.detach().cpu().numpy().astype(np.int64)

        rows = []
        for idx in range(len(cls)):
            coco_class_id = int(cls[idx])
            confidence = float(conf[idx])
            if coco_class_id == _YOLO_PERSON_CLASS_ID:
                if confidence < person_threshold:
                    continue
                hearthlight_class_id = 0
            elif coco_class_id in _YOLO_BAG_CLASS_IDS:
                if confidence < bag_threshold:
                    continue
                hearthlight_class_id = 1
            else:
                continue

            x1, y1, x2, y2 = xyxy[idx].tolist()
            rows.append([x1, y1, x2, y2, confidence, hearthlight_class_id])

        if not rows:
            return np.zeros((0, 6), dtype=np.float32)

        detections = np.asarray(rows, dtype=np.float32)
        keep_indices = []
        for class_id in (0, 1):
            class_indices = np.flatnonzero(detections[:, 5] == class_id)
            keep = _nms_numpy(
                detections[class_indices, :4],
                detections[class_indices, 4],
                _YOLO_NMS_IOU_THRESHOLD,
            )
            keep_indices.extend(class_indices[keep].tolist())
        if not keep_indices:
            return np.zeros((0, 6), dtype=np.float32)
        return detections[np.asarray(keep_indices, dtype=np.int64)]

    def infer(self, frames):
        if self._ultralytics_model is not None:
            return self._infer_ultralytics(frames)
        if self._hog_descriptor is not None:
            return self._infer_hog(frames)
        inputs = [frame.array for frame in frames]
        return self.model(inputs, self.conf_dict)


ADAPTERS = {
    "rtdetr_detector": RTDetrDetectorAdapter,
    "yolox_detector": RTDetrDetectorAdapter,
}


class Detector:
    def __init__(self, cfg):
        logger.debug("Initializing", extra={"task": self.__class__.__name__})
        self.cfg = cfg
        self.registry_bundle = load_registry_bundle()
        has_gpu = (
            bool(shutil.which("nvidia-smi"))
            and subprocess.run(["nvidia-smi"], capture_output=True).returncode == 0
        )
        defaults = build_default_bindings(
            self.registry_bundle,
            has_gpu=has_gpu,
            runtime_model_bindings=getattr(cfg, "model_bindings", None),
        )
        self.default_model_key = defaults.get(MODEL_STAGE_DETECTOR)
        self.camera_model_keys = {}
        self.camera_tasks = {}
        self.adapters = {}
        for cam_id, camera_cfg in cfg.input.cameras.items():
            camera_dict = dict(camera_cfg)
            model_key = camera_dict.get("detector_model_key") or self.default_model_key
            self.camera_model_keys[cam_id] = model_key
            self.camera_tasks[cam_id] = {
                str(task).strip().upper() for task in camera_dict.get("tasks", [])
            }
            if not model_key:
                continue
            if model_key not in self.adapters:
                registration = get_registration(
                    self.registry_bundle, MODEL_STAGE_DETECTOR, model_key
                )
                if registration is None:
                    raise ValueError(f"missing detector registration {model_key}")
                runtime = dict(registration.get("runtime") or {})
                cfg_device = cfg.rtdetr.get("device", runtime.get("device", "cuda:0"))
                runtime.setdefault("device", cfg_device)
                runtime.setdefault(
                    "backend",
                    cfg.rtdetr.get(
                        "backend",
                        "trt" if "cuda" in str(cfg_device).lower() else "onnx",
                    ),
                )
                runtime.setdefault(
                    "precision",
                    cfg.rtdetr.get(
                        "precision",
                        "fp16" if "cuda" in str(cfg_device).lower() else "fp32",
                    ),
                )
                if cfg.rtdetr.get("half") is False:
                    runtime["precision"] = "fp32"
                if "cuda" not in str(runtime["device"]).lower() and runtime["backend"] == "trt":
                    runtime["backend"] = "onnx"
                if "cuda" not in str(runtime["device"]).lower() and runtime["precision"] == "fp16":
                    runtime["precision"] = "fp32"
                registration = dict(registration)
                registration["runtime"] = runtime
                adapter_cls = ADAPTERS[registration.get("adapter", "rtdetr_detector")]
                self.adapters[model_key] = adapter_cls(cfg, registration)
        logger.debug("Initialized", extra={"task": self.__class__.__name__})

    def __call__(self, frames):
        track_results = [None] * len(frames.frames)
        detection_results = [None] * len(frames.frames)
        frames_by_model = {}
        for index, frame in enumerate(frames.frames):
            model_key = self.camera_model_keys.get(frame.cam_id, self.default_model_key)
            frames_by_model.setdefault(model_key, []).append((index, frame))

        for model_key, indexed_frames in frames_by_model.items():
            if not model_key:
                for frame_index, _frame in indexed_frames:
                    track_results[frame_index], detection_results[frame_index] = self.post_process_single(
                        np.zeros((0, 6), dtype=np.float32),
                        frames.frames[frame_index],
                        set(),
                    )
                continue
            adapter = self.adapters[model_key]
            frame_batch = [frame for _, frame in indexed_frames]
            outputs = adapter.infer(frame_batch)
            for (frame_index, frame), output in zip(indexed_frames, outputs):
                track_results[frame_index], detection_results[frame_index] = self.post_process_single(
                    output,
                    frame,
                    adapter.track_class_ids,
                )
        return track_results, detection_results

    def post_process_single(self, output, frame, track_class_ids):
        output = np.asarray(output, dtype=np.float32)
        if output.size == 0:
            output = np.zeros((0, 6), dtype=np.float32)
        elif output.ndim == 1:
            output = output.reshape(-1, 6)
        clip_coords(output, frame.array.shape)
        allowed_tasks = self.camera_tasks.get(frame.cam_id, {Tasks.PERSON})
        track_classes = {
            class_id: clss
            for class_id, clss in self.cfg.rtdetr.names.items()
            if clss.upper() in allowed_tasks and class_id in track_class_ids
        }
        detection_classes = {
            class_id: clss
            for class_id, clss in self.cfg.rtdetr.names.items()
            if clss.upper() in allowed_tasks and class_id not in track_class_ids
        }
        track_array = self.filter(output, track_classes)
        det_array = self.filter(output, detection_classes)
        detections = [
            Detection(
                bbox=det[:4],
                clss=detection_classes[det[5]].upper(),
                cam_id=frame.cam_id,
                confidence=float(det[4]) if len(det) > 4 else None,
            )
            for det in det_array
        ]
        return track_array, detections

    def filter(self, array, classes):
        mask = np.zeros(array.shape[0], dtype=bool)

        for class_id in classes:
            key_mask = (array[:, 5] == class_id)
            mask |= key_mask

        return array[mask]
