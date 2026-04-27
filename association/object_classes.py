from __future__ import annotations
from collections import defaultdict

import numpy as np

from shared.constants import DetectorClasses
from shared.models.DataModels import TrackInstance


class TrackedObject:
    _cam_refresh_interval = 200

    def __init__(self, id: int, object_instance: TrackInstance, time_delta: float):
        self.id = id

        cam_id = object_instance.cam_id
        bbox = object_instance.bbox

        # volatile attributes
        self.cam_ids = {object_instance.cam_id}
        self.new_cam_ids = []
        self.track_ids = {cam_id: object_instance.track_id}
        self.bbox = {cam_id: bbox}
        bbox_arr = np.array(bbox)
        self.diagonals = {cam_id: np.linalg.norm(bbox_arr[2:] - bbox_arr[:2])}
        self.centroids = {cam_id: (bbox_arr[:2] + bbox_arr[2:]) / 2}

        # sticky attributes
        self.cam_timestamps = {cam_id: object_instance.timestamp}
        self.cam_frame_ids = {cam_id: object_instance.frame_id}
        self.zone_ids = {cam_id: object_instance.zone_id}
        self.prev_centroids = {}
        self.hits = 1
        self.time_seen = time_delta

    def update(self, object_instance: TrackInstance, time_delta: float):
        cam_id = object_instance.cam_id
        bbox = object_instance.bbox

        self.cam_ids.add(cam_id)
        if (
            object_instance.timestamp - self.cam_timestamps.get(cam_id, float("-inf"))
            > TrackedObject._cam_refresh_interval
        ):
            self.new_cam_ids.append(cam_id)
        self.track_ids[cam_id] = object_instance.track_id
        self.bbox[cam_id] = bbox
        bbox_arr = np.array(bbox)
        self.diagonals[cam_id] = np.linalg.norm(bbox_arr[2:] - bbox_arr[:2])
        self.centroids[cam_id] = (bbox_arr[:2] + bbox_arr[2:]) / 2

        self.cam_timestamps[cam_id] = object_instance.timestamp
        self.cam_frame_ids[cam_id] = object_instance.frame_id
        self.zone_ids[cam_id] = object_instance.zone_id
        self.hits += 1
        self.time_seen += time_delta

    def update_age(self):
        if self.centroids:
            self.prev_centroids = self.centroids.copy()
        self.cam_ids = set()
        self.new_cam_ids = []
        self.track_ids = {}
        self.bbox = {}
        self.diagonals = {}
        self.centroids = {}

    def merge(self, other: TrackedObject):
        if self.last_timestamp < other.last_timestamp:
            self.prev_centroids = other.prev_centroids

        other_cam = other.last_cam_id
        other_frame = other.cam_frame_ids[other_cam]
        if other_frame > self.cam_frame_ids.get(other_cam, 0):
            self.cam_frame_ids[other_cam] = other_frame
            self.cam_timestamps[other_cam] = other.cam_timestamps[other_cam]
            self.zone_ids[other_cam] = other.zone_ids[other_cam]

        self.hits += other.hits
        self.time_seen += other.time_seen

    def to_array(self):
        array_list = []
        for cam_id in self.bbox:
            array_list.append(np.hstack([self.bbox[cam_id], self.id, cam_id]))
        return np.vstack(array_list)

    def get_track_ids(self):
        return list(self.track_ids.values())

    @property
    def last_timestamp(self):
        return max(self.cam_timestamps.values())

    @property
    def last_cam_id(self):
        return max(self.cam_timestamps, key=lambda x: self.cam_timestamps[x])

    @property
    def last_frame_id(self):
        return max(self.cam_frame_ids.values())

    @classmethod
    def set_cam_refresh_interval(cls, cam_refresh_interval: int):
        cls._cam_refresh_interval = cam_refresh_interval


class Person:

    def __init__(self, object_instance: TrackInstance, time_delta: float):
        assert object_instance.real_id is not None
        self.id = object_instance.real_id

        self.data = TrackedObject(self.id, object_instance, time_delta)

        self.clss = DetectorClasses.PERSON
        self.paired_persons = set()

        self.gun_threat = 0

    def update(self, object_instance: TrackInstance, time_delta: float):
        self.data.update(object_instance, time_delta)

        self.gun_threat -= time_delta * 0.1
        self.gun_threat = max(0, self.gun_threat)

    def merge(self, other: Person):
        self.data.merge(other.data)
        self.gun_threat += other.gun_threat

    def add_pair(self, other: Person):
        self.paired_persons.add(other)


class Bag:
    def __init__(self, object_instance: TrackInstance, time_delta: float):
        assert object_instance.real_id is not None
        self.id = object_instance.real_id

        self.data = TrackedObject(self.id, object_instance, time_delta)

        self.clss = DetectorClasses.BAG
        self.owner: Person | None = None
        self.owners: set[Person] = set()
        self.owner_scores: dict[int, float] = defaultdict(float)
        self.last_time_attended = object_instance.timestamp
        self.unattended = False
        self.first_check = False

    def update(self, object_instance: TrackInstance, time_delta: float):
        self.data.update(object_instance, time_delta)

    def merge(self, other: Bag):
        self.data.merge(other.data)
        if self.owner is None:
            self.owner = other.owner
            self.owner_scores.update(other.owner_scores)
            self.owners.update(other.owners)
            if other.owner is not None:
                self.last_time_attended = other.last_time_attended
                self.unattended = other.unattended
