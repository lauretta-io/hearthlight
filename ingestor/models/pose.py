from types import SimpleNamespace
import logging

import cv2
import numpy as np
import onnxruntime as ort

from ...shared.utils.download_weights import get_model_weights
from ...shared.constants import DetectorClasses
from ...shared.utils.matching import iou_distance, linear_assignment

logger = logging.getLogger(__name__)


class PoseDetector:
    def __init__(self, cfg):
        logger.debug("Initializing", extra={"task": self.__class__.__name__})

        providers = ["CUDAExecutionProvider"] if "cuda" in cfg.pose.device else []
        providers.append("CPUExecutionProvider")
        model_path = get_model_weights(cfg.pose.model_name)
        self.session = ort.InferenceSession(model_path, providers=providers)

        self.shape_attrs = {}

        logger.debug("Initialized", extra={"task": self.__class__.__name__})

    def get_shape_attrs(self, image):
        if image.shape not in self.shape_attrs:
            self.shape_attrs[image.shape] = self.create_shape_attrs(image)
        return self.shape_attrs[image.shape]

    def create_shape_attrs(self, image, model_shape=(640, 640)):
        original_shape = (image.shape[1], image.shape[0])  # the following expects W, H
        ratio = float(max(model_shape)) / max(original_shape)
        assert ratio > 0
        new_shape = tuple([int(x * ratio) for x in original_shape])
        delta_w = model_shape[0] - new_shape[0]
        delta_h = model_shape[1] - new_shape[1]
        top, bottom = delta_h // 2, delta_h - (delta_h // 2)
        left, right = delta_w // 2, delta_w - (delta_w // 2)
        return SimpleNamespace(
            ratio=ratio,
            new_shape=new_shape,
            top=top,
            bottom=bottom,
            left=left,
            right=right,
        )

    def __call__(self, frames, tracks):
        frame_arrays = [frame.array for frame in frames.frames]
        bboxes, keypoints = self.get_keypoints(frame_arrays)
        return self.link_keypoints(keypoints, bboxes, tracks)

    def get_keypoints(self, images):
        input = self.preprocess(images)
        _bboxes, _keypoints = self.session.run(None, {"input": input})
        bboxes, keypoints = self.postprocess(_bboxes, _keypoints, images)
        return bboxes, keypoints

    def preprocess(self, images):
        padded_arrays = [self.resize_with_pad(image) for image in images]
        rgb_arrays = [cv2.cvtColor(array, cv2.COLOR_BGR2RGB) for array in padded_arrays]
        inputs = [array.astype(np.float32).transpose(2, 0, 1) for array in rgb_arrays]
        return np.array(inputs)

    def resize_with_pad(self, image, pad_color=(114, 114, 114)):
        shape_attrs = self.get_shape_attrs(image)

        image = cv2.resize(image, shape_attrs.new_shape)
        image = cv2.copyMakeBorder(
            image,
            shape_attrs.top,
            shape_attrs.bottom,
            shape_attrs.left,
            shape_attrs.right,
            cv2.BORDER_CONSTANT,
            value=pad_color,
        )
        return image

    def postprocess(self, bboxes, keypoints, images):
        bbox_list = [np.unique(cam_bboxes, axis=0) for cam_bboxes in bboxes]
        keypoints_list = [
            np.unique(cam_keypoints, axis=0) for cam_keypoints in keypoints
        ]
        processed_bboxes, processed_keypoints = [], []

        for bboxes, keypoints, image in zip(bbox_list, keypoints_list, images):
            shape_attrs = self.get_shape_attrs(image)

            bboxes[..., 0] -= shape_attrs.left
            bboxes[..., 2] -= shape_attrs.left
            bboxes[..., 1] -= shape_attrs.top
            bboxes[..., 3] -= shape_attrs.top

            bboxes[..., 0:4] /= shape_attrs.ratio

            width = image.shape[1]
            height = image.shape[0]
            fudge_factor = 0.05
            x_max = width * (1.0 + fudge_factor)
            x_min = -width * fudge_factor
            y_max = height * (1.0 + fudge_factor)
            y_min = -height * fudge_factor

            # fmt: off
            mask = (
                (bboxes[..., 0] > x_min) & (bboxes[..., 0] < x_max) &
                (bboxes[..., 1] > y_min) & (bboxes[..., 1] < y_max) &
                (bboxes[..., 2] > x_min) & (bboxes[..., 2] < x_max) &
                (bboxes[..., 3] > y_min) & (bboxes[..., 3] < y_max)
            )
            # fmt: on

            bboxes = bboxes[mask]
            keypoints = keypoints[mask, ...]

            keypoints[..., 0] -= shape_attrs.left
            keypoints[..., 1] -= shape_attrs.top

            keypoints[..., 0:2] /= shape_attrs.ratio

            processed_bboxes.append(bboxes)
            processed_keypoints.append(keypoints)

        return processed_bboxes, processed_keypoints

    def link_keypoints(self, keypoints, bboxes, tracks):
        for cam_keys, cam_bboxes, cam_tracks in zip(keypoints, bboxes, tracks):
            person_tracks = [
                track for track in cam_tracks if track.clss == DetectorClasses.PERSON
            ]
            if person_tracks:
                track_bboxes = np.array([track.bbox for track in person_tracks])
                cost_matrix = iou_distance(cam_bboxes[:, :4], track_bboxes)
                matches, _, _ = linear_assignment(cost_matrix, 0.9)
                for key_index, box_index in matches:
                    track = person_tracks[box_index]
                    keys = cam_keys[key_index]
                    track.keypoints = keys
                    track.body_visible = self.check_body(keys)
                    track.face_visible = self.check_face(keys)
        return tracks

    def check_body(self, keypoints):
        if keypoints is None:
            return False
        if np.mean(keypoints[:, 2]) < 0.7:
            return False
        return True

    def check_face(self, keypoints):
        if keypoints is None:
            return False
        # 3 is left ear, 4 is right ear
        # hopefully not upside down
        if keypoints[4, 0] > keypoints[3, 0]:
            return False
        return True
