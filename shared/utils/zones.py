from collections import defaultdict
import warnings

import cv2
import numpy as np
from shapely.geometry import Polygon, Point

from ..models.SQLModels import CameraRecording


class ZonePerspective:
    def __init__(self, zone_id, vertices, width, height):
        self.zone_id = zone_id
        self.vertices = self.get_scaled_vertices(vertices, width, height)
        self.poly = Polygon(self.vertices)

    def get_scaled_vertices(self, vertices, width, height):
        vertices = np.array(vertices)
        vertices[:, 0] *= width
        vertices[:, 1] *= height
        vertices = vertices.astype(int)
        return vertices

    def contains(self, point):
        point = Point(point)
        return self.poly.contains(point)


class ZoneAssigner:
    def __init__(self, cameras: list[CameraRecording], zone_config):
        self.cam_zones = {cam.cam_id: [] for cam in cameras}
        self.poly_dict = {}

        cam_sizes = {cam.cam_id: (cam.width, cam.height) for cam in cameras}

        for zone_id, zone_cfg in zone_config.items():
            for cam_id in zone_cfg.get("cameras", {}):
                if cam_id not in self.cam_zones:
                    warnings.warn(
                        f"zone {zone_id} includes nonexistent camera {cam_id} "
                    )
                    continue
                self.cam_zones[cam_id].append(
                    ZonePerspective(
                        zone_id,
                        zone_cfg.cameras[cam_id],
                        cam_sizes[cam_id][0],
                        cam_sizes[cam_id][1],
                    )
                )

    def get_zone(self, bbox, cam_id):
        if cam_id not in self.cam_zones:
            return 0
        bbox_bottom_center = ((bbox[0] + bbox[2]) / 2, bbox[3])
        for zone in self.cam_zones[cam_id]:
            if zone.contains(bbox_bottom_center):
                return zone.zone_id
        return 0  # the default 'wasteland' zone

    def draw(self, img, cam_id):
        for zone in self.cam_zones[cam_id]:
            cv2.polylines(
                img, [zone.vertices], isClosed=True, color=(0, 255, 0), thickness=2
            )
        return img


class ZoneManager:
    def __init__(self, cameras: list[CameraRecording], zone_config):
        self.zone_checker = ZoneAssigner(cameras, zone_config)
        self.zones = {zone_id for zone_id in zone_config}
        self.zones.add(0)
        # {real_id: {cam_id: {zone_id: capped_time_in_zone}}}
        self.zone_scores = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        # {real_id: {cam_id: {zone_id: time_in_zone}}}
        self.zone_times = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        self.lag_time = 20

    def add_zones(self, tracks):
        for track in tracks:
            real_id = (
                track.real_id if track.real_id is not None else -1 * track.track_id
            )
            current_zone_id = self.zone_checker.get_zone(track.bbox, track.cam_id)
            zone_scores = self.zone_scores[real_id][track.cam_id]
            zone_scores[current_zone_id] = min(
                zone_scores[current_zone_id] + 2, self.lag_time + 1
            )
            track.zone_id = max(zone_scores, key=lambda x: zone_scores.get(x, 0))
            self.zone_times[real_id][track.cam_id][track.zone_id] += (
                2  # we decrement by 1 each frame
            )

        self.prune_zone_scores(self.zone_scores)
        self.prune_zone_times(self.zone_times, self.zone_scores)

        return tracks

    def prune_zone_scores(self, d):
        for key, value in list(d.items()):
            if isinstance(value, dict):
                self.prune_zone_scores(value)
            else:
                value = max(value - 1, 0)
                d[key] = value
            if not value:
                del d[key]

    def prune_zone_times(self, d, model):
        for key, value in list(d.items()):
            if key not in model:
                del d[key]
            elif isinstance(value, dict):
                self.prune_zone_times(value, model[key])
            else:
                value = max(value - 1, 0)
                d[key] = value
