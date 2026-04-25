import inspect
import numpy as np

from hearthlight_model_zoo.feature_extractors import FeatureExtractor as FE


class FeatureExtractor:
    def __init__(self, cfg):
        device = cfg.get("device", "cuda:0")
        backend = cfg.get("backend", "onnx")
        precision = cfg.get("precision", "fp16" if "cuda" in str(device).lower() else "fp32")
        kwargs = {"backend": backend, "precision": precision}
        try:
            signature = inspect.signature(FE)
            if "device" in signature.parameters:
                kwargs["device"] = device
        except (TypeError, ValueError):
            pass
        self.model = FE(cfg.model_name, **kwargs)

    def extract(self, crops):
        if not crops:
            return np.array([[]])
        return self.model(crops)

    def extract_frames(
        self, cam_crops
    ) -> list[list[np.ndarray[tuple[int], np.dtype[np.float32 | np.float16]]]]:
        cam_features = [[] for _ in cam_crops]
        cam_list = []
        crop_list = []

        for cam_num, crops in enumerate(cam_crops):
            cam_list += [cam_num] * len(crops)
            crop_list += crops

        if not crop_list:
            return cam_features

        features_array = self.model(crop_list)

        for i, cam in enumerate(cam_list):
            cam_features[cam].append(features_array[i])

        return cam_features
