import logging
import shutil
import subprocess

import numpy as np

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

    def infer(self, frames):
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
