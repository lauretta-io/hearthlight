from collections import defaultdict
import logging

import numpy as np

from ...shared.models.DataModels import TrackInstance
from hearthlight_model_zoo.trackers import get_tracker
from ...shared.utils.model_registry import (
    MODEL_STAGE_TRACKER,
    build_default_bindings,
    get_registration,
    load_registry_bundle,
    resolve_tracker_name,
)

logger = logging.getLogger(__name__)


class Tracker:
    def __init__(self, cfg, camera_ids: list[int]):
        try:
            logger.debug("Initializing", extra={"task": self.__class__.__name__})
            self.classes = cfg.classes
            self.registry_bundle = load_registry_bundle()
            defaults = build_default_bindings(
                self.registry_bundle,
                runtime_model_bindings=getattr(cfg._get_parent(), "model_bindings", None),
            )
            default_model_key = defaults.get(MODEL_STAGE_TRACKER)
            self.tracker_list = []
            input_cfg = cfg._get_parent().input
            for cam_id in camera_ids:
                camera_cfg = dict(input_cfg.cameras[cam_id])
                model_key = camera_cfg.get("tracker_model_key") or default_model_key
                legacy_tracker_name = cfg.get("tracker") or cfg.get("track_method")
                registration = get_registration(
                    self.registry_bundle, MODEL_STAGE_TRACKER, model_key
                )
                tracker_name = resolve_tracker_name(
                    registration,
                    model_key,
                    legacy_tracker_name=legacy_tracker_name,
                )
                if tracker_name is None:
                    raise ValueError(f"missing tracker registration {model_key}")
                if registration is None:
                    logger.warning(
                        "Tracker registration %s was not found; falling back to legacy tracker name %s",
                        model_key,
                        tracker_name,
                        extra={"task": self.__class__.__name__},
                    )
                self.tracker_list.append(
                    {clss: get_tracker(tracker_name) for clss in cfg.classes}
                )
            logger.debug("Initialized", extra={"task": self.__class__.__name__})
        except Exception as e:
            logger.error(e, extra={"task": self.__class__.__name__})
            raise

    def update(self, dets, features, frames, frame_id):
        tracks = []
        for frame, cam_dets, cam_features, cam_trackers in zip(
            frames, dets, features, self.tracker_list
        ):
            clss_dets = defaultdict(list)
            clss_features = defaultdict(list)
            for det, feature in zip(cam_dets, cam_features):
                clss_dets[det[5]].append(det[0:5])
                clss_features[det[5]].append(feature)

            cam_tracks = []
            for clss_id, tracker in cam_trackers.items():
                if clss_dets[clss_id]:
                    class_dets = np.array(clss_dets[clss_id])
                    class_features = np.array(clss_features[clss_id])
                else:
                    class_dets = np.empty((0, 5))
                    class_features = np.empty((0, 2)).astype(np.float32)
                track_array = tracker.update(class_dets, class_features)

                bbox_to_idx = {tuple(det[:4]): i for i, det in enumerate(class_dets)}

                for track in track_array:
                    track_bbox = tuple(track[:4])
                    det_idx = bbox_to_idx[track_bbox]
                    cam_tracks.append(
                        TrackInstance(
                            track_id=track[4],
                            bbox=track[0:4].tolist(),
                            cam_id=frame.cam_id,
                            clss=self.classes[clss_id].upper(),
                            timestamp=frame.timestamp,
                            frame_id=frame_id,
                            feature=class_features[det_idx],
                        )
                    )
            tracks.append(cam_tracks)
        return tracks
