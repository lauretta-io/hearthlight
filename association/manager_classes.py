from __future__ import annotations
from collections import defaultdict
import logging
import math
from typing import Any, Type

import numpy as np

from .object_classes import Person, Bag
from .incident_classes import Incident, GunIncident, UnattendedBag
from shared.models.DataModels import TrackInstance, Frames, ResolutionMessage
from shared.constants import (
    DetectorClasses,
    IncidentStatus,
    IncidentType,
    IncidentTypeStr,
)
from shared.utils.bbox import IoA, bbox_centroid, xyxy2xywh

logger = logging.getLogger(__name__)


class PersonManager:
    def __init__(self, cfg):
        self.persons: dict[int, Person] = {}
        self.temp_persons: dict[int, Person] = {}

        self.temp_to_id: dict[int, int] = {}

        self.id_guesses: dict[int, int] = {}

        self.visible_persons: dict[int, Person] = {}
        self.visible_persons_array: np.ndarray | None = None

        self.cfg = cfg

        self.incidents = IncidentManager(self)

    def __call__(self, person_id: int):
        if person_id < 0:
            return self.temp_persons[person_id]
        return self.persons[person_id]

    def get_person_array(self):
        if self.visible_persons_array is None:
            array_list = []
            if self.visible_persons is not None:
                for person_id in self.visible_persons:
                    if person_id < 0:
                        person = self.temp_persons[person_id]
                    else:
                        person = self.persons[person_id]
                    array_list.append(person.data.to_array())
            if len(array_list) == 0:
                return np.array([])
            self.visible_persons_array = np.vstack(array_list)

        return self.visible_persons_array

    def update(
        self,
        person_tracks: list[TrackInstance],
        id_updates: dict[int, int],
        id_guesses: dict[int, int],
        frame_info: Frames,
    ):
        self.visible_persons_array = None

        self.id_guesses.update(id_guesses)

        for temp_id, persistent_id in id_updates.items():
            if temp_id in self.id_guesses:
                self.id_guesses.pop(temp_id)
            temp_person = self.temp_persons.pop(temp_id)
            if persistent_id not in self.persons:
                temp_person.id = persistent_id
                self.persons[persistent_id] = temp_person
            else:
                self.persons[persistent_id].merge(temp_person)
            self.temp_to_id[temp_id] = persistent_id

        temps = []
        olds = []

        for track in person_tracks:
            assert track.real_id is not None
            if track.real_id < 0:
                temps.append(track)
            else:
                olds.append(track)

        temp_persons = add_or_update(temps, self.temp_persons, frame_info, Person)
        persons = add_or_update(olds, self.persons, frame_info, Person)

        self.visible_persons = temp_persons
        self.visible_persons.update(persons)

    def get_pairwise_distances(self, persons: dict[int, Person]):
        distances = []

        for person1_id, person1 in persons.items():
            for person2_id, person2 in persons.items():
                if person2_id <= person1_id:
                    continue
                for cam_id, bbox1 in person1.data.bbox.items():
                    if cam_id not in person2.data.bbox:
                        continue
                    bbox2 = person2.data.bbox[cam_id]
                    distance_score = self.get_distance_score(bbox1, bbox2)
                    distances.append([cam_id, person1, person2, distance_score])

        return distances

    def get_distance_score(self, bbox1: np.ndarray, bbox2: np.ndarray):
        pixel_distance = self.get_centroid_distance(bbox1, bbox2)
        area1 = self.get_bbox_area(bbox1)
        area2 = self.get_bbox_area(bbox2)
        area = max(area1, area2)
        sqrt_area = math.sqrt(area)
        score = sqrt_area / (pixel_distance + 1)
        return score

    def get_centroid_distance(self, bbox1: np.ndarray, bbox2: np.ndarray):
        centroid1 = np.array([bbox1[0] + bbox1[2], bbox1[1] + bbox1[3]]) / 2
        centroid2 = np.array([bbox2[0] + bbox2[2], bbox2[1] + bbox2[3]]) / 2
        return np.linalg.norm(centroid1 - centroid2)

    def get_bbox_area(self, bbox: np.ndarray):
        return (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])

    def get_real_id(self, track_id: int):
        for id, person in self.persons.items():
            if track_id in person.data.get_track_ids():
                return id


class BagManager:
    def __init__(
        self, cfg, person_manager: PersonManager, incident_manager: IncidentManager
    ):
        self.bags: dict[int, Bag] = {}
        self.temp_bags: dict[int, Bag] = {}
        self.visible_bags: dict[int, Bag] = {}

        self.person_manager = person_manager

        self.incidents = incident_manager

        self.radius = cfg.association.bag.radius
        self.lamb = cfg.association.bag.association_lamb
        self.ownership_thresh = cfg.association.bag.association_threshold

        self.unattended_time = cfg.association.bag.unattended_time

    def update(
        self,
        bag_tracks: list[TrackInstance],
        id_updates: dict[int, int],
        frame_info: Frames,
    ):
        for temp_id, persistent_id in id_updates.items():
            temp_bag = self.temp_bags.pop(temp_id)
            if persistent_id not in self.bags:
                temp_bag.id = persistent_id
                self.bags[persistent_id] = temp_bag
            else:
                self.bags[persistent_id].merge(temp_bag)

        temps = []
        olds = []

        for track in bag_tracks:
            assert track.real_id is not None
            if track.real_id < 0:
                temps.append(track)
            else:
                olds.append(track)

        temp_bags = add_or_update(temps, self.temp_bags, frame_info, Bag)
        bags = add_or_update(olds, self.bags, frame_info, Bag)

        self.visible_bags = temp_bags
        self.visible_bags.update(bags)

    def get_new_bag_owners(self, frame_info: Frames):
        new_pairs: list[tuple[int, int]] = []

        if not self.person_manager.visible_persons:
            return new_pairs

        person_array = self.person_manager.get_person_array()

        for _, bag in self.visible_bags.items():
            if bag.owner is not None:
                continue
            for cam_id, bbox in bag.data.bbox.items():
                for person_id in get_close_persons(
                    bag, cam_id, person_array, self.radius
                ):
                    person = self.person_manager(person_id)
                    association_score = get_association(
                        bbox, person.data.bbox[cam_id], self.lamb
                    )
                    time_delta = frame_info.get_frame(cam_id).time_delta
                    bag.owner_scores[person_id] += association_score * time_delta
            if bag.owner_scores:
                owner_id = max(bag.owner_scores, key=lambda x: bag.owner_scores[x])
                if bag.owner_scores[owner_id] > self.ownership_thresh:
                    bag.owner = self.person_manager(owner_id)
                    new_pairs.append((bag.id, owner_id))
                    bag.owners = {bag.owner} | bag.owner.paired_persons
            if not bag.first_check and bag.data.time_seen > 1:
                bag.first_check = True
                if bag.owner is None and bag.owner_scores:
                    sorted_owner_ids = sorted(
                        bag.owner_scores,
                        key=lambda x: bag.owner_scores[x],
                        reverse=True,
                    )
                    for owner_id in sorted_owner_ids:
                        try:
                            bag.owner = self.person_manager(owner_id)
                            break
                        except KeyError:
                            continue
                    if bag.owner is not None:
                        new_pairs.append((bag.id, bag.owner.id))
                        bag.owners = {bag.owner} | bag.owner.paired_persons

        return new_pairs

    def get_new_unattended_bags(self):
        incidents = []

        for _, bag in self.visible_bags.items():
            if bag.data.hits <= 1:
                continue

            if bag.owner is None:
                # for now, this does nothing
                bag.last_time_attended = bag.data.last_timestamp

            else:
                owner = bag.owner
                # owner is a temp id, so they should be visible with that id
                if owner.id < 0:
                    if owner.id in self.person_manager.visible_persons:
                        # checks if owner is in same camera
                        if bag.data.last_cam_id in owner.data.cam_ids:
                            bag.last_time_attended = bag.data.last_timestamp
                            break
                    # switch bag over to permanent id owner
                    elif owner.id in self.person_manager.temp_to_id:
                        bag.owner = self.person_manager(
                            self.person_manager.temp_to_id[owner.id]
                        )
                        print(f"Switching owner id {owner.id} to {bag.owner.id} for bag {bag.id}")
                # owner is a persistent id, so we check the guesses about the current
                # persistent ids
                else:
                    for p_id, person in self.person_manager.visible_persons.items():
                        if (
                            self.person_manager.id_guesses.get(p_id, p_id)
                            != owner.id
                        ):
                            continue
                        if bag.data.last_cam_id in person.data.cam_ids:
                            bag.last_time_attended = bag.data.last_timestamp
                            break

            if bag.data.last_timestamp - bag.last_time_attended > self.unattended_time:
                if bag.unattended:
                    continue
                bag.unattended = True
                if bag.owner is None:
                    scores = bag.owner_scores
                    possible_owners = sorted(
                        scores, key=lambda x: scores[x], reverse=True
                    )[:5]
                    bag.owners = {self.person_manager(id) for id in possible_owners}
                incident = UnattendedBag(bag)
                incidents.append(incident)
            elif bag.unattended:
                self.incidents.resolve_bag(bag.id)

        return incidents


class GunManager:
    def __init__(
        self, cfg, person_manager: PersonManager, incident_manager: IncidentManager
    ):
        self.person_manager = person_manager
        self.incidents = incident_manager
        self.threshold = cfg.association.gun.threat_threshold

    def get_new_gunmen(self, gun_dets, frame_info):
        if gun_dets is None:
            return []

        new_threats = []

        cam_guns = defaultdict(list)
        for gun_det in gun_dets:
            cam_guns[gun_det.cam_id].append(gun_det)

        for person_id, person in self.person_manager.visible_persons.items():
            if self.incidents.has_incident(person_id, IncidentType.GUN):
                continue
            for cam_id, bbox in person.data.bbox.items():
                for gun in cam_guns[cam_id]:
                    if check_overlap(gun.bbox, bbox, extension=True):
                        # threat counter represents time seen with gun
                        person = self.person_manager(person_id)
                        threat_increment = frame_info.get_frame(cam_id).time_delta
                        person.gun_threat += threat_increment
                        if self.incidents.has_incident(person_id, IncidentType.GUN):
                            break
                        elif person.gun_threat > self.threshold:
                            incident = GunIncident(person)
                            new_threats.append(incident)
                        break

        return new_threats


class IncidentManager:
    def __init__(self, person_manager: PersonManager):
        self.person_manager = person_manager
        self.incidents: dict[int, Incident] = {}
        self.person_incident_map: dict[int, set[int]] = defaultdict(set)
        self.incident_person_map: dict[int, set[int]] = defaultdict(set)
        self.bag_incident_map: dict[int, int] = {}
        self.child_incident_map: dict[int, int] = {}

    def update(
        self,
        new_incidents: list[Incident],
        external_resolutions: list[ResolutionMessage],
    ):
        deletes = []

        system_resolutions: list[Incident] = []
        for id, incident in self.incidents.items():
            if incident.resolved:
                if incident.status == IncidentStatus.UNCONFIRMED:
                    system_resolutions.append(incident)
                    deletes.append(id)
                else:
                    incident.resolved = False

        for resolution in external_resolutions:
            incident_id = resolution.incident_id
            if incident_id in self.incidents:
                incident = self.incidents[incident_id]
                if resolution.status and resolution.status != IncidentStatus.RESOLVED:
                    incident.status = resolution.status
                    incident.resolved = False
                else:
                    incident.resolve()
                    deletes.append(incident_id)

        for id in deletes:
            entity_ids = self.incident_person_map.pop(id)
            for entity_id in entity_ids:
                self.person_incident_map[entity_id].remove(id)
            del self.incidents[id]

        for incident in new_incidents:
            self.incidents[incident.id] = incident
            for entity in incident.entities.entities:
                if entity.clss == DetectorClasses.PERSON:
                    self.person_incident_map[entity.id].add(incident.id)
                    self.incident_person_map[incident.id].add(entity.id)
                elif entity.clss == DetectorClasses.BAG:
                    self.bag_incident_map[entity.id] = incident.id

        return system_resolutions

    def update_ids(self, id_updates: dict[int, int]):
        for temp_id, persistent_id in id_updates.items():
            if temp_id not in self.person_incident_map:
                continue
            incident_ids = self.person_incident_map.pop(temp_id)
            for incident_id in incident_ids:
                if incident_id not in self.incidents:
                    logger.warning(f"UPDATE IDS: incident {incident_id} not found for person {temp_id}, {persistent_id}")
                    continue
                incident = self.incidents[incident_id]
                incident.entities.roles[persistent_id] = incident.entities.roles.pop(
                    temp_id
                )
                for idx, entity in enumerate(incident.entities.entities):
                    if entity.id == temp_id:
                        incident.entities[idx] = self.person_manager(persistent_id)
                        break
                self.incident_person_map[incident_id].remove(temp_id)
                self.incident_person_map[incident_id].add(persistent_id)
            self.person_incident_map[persistent_id].update(incident_ids)

    def has_incident(self, person_id: int, incident_type: IncidentTypeStr):
        if person_id not in self.person_incident_map:
            return False
        incident_ids = self.person_incident_map[person_id]
        for incident_id in incident_ids:
            if incident_id not in self.incidents:
                print(f"HAS INCIDENT: incident {incident_id} not found for person {person_id}")
                continue
            if self.incidents[incident_id].incident_type == incident_type:
                return True
        return False

    def resolve_bag(self, bag_id: int):
        incident_id = self.bag_incident_map.pop(bag_id)
        self.incidents[incident_id].resolve()


def add_or_update(
    objects: list[TrackInstance], store: dict[int, Any], frame_info: Frames, clss: Type
):
    for id in store:
        store[id].data.update_age()

    visible_objects = {}
    for obj in objects:
        id = obj.real_id
        assert id is not None
        time_delta = frame_info.get_frame(obj.cam_id).time_delta
        if id in store:
            store[id].update(obj, time_delta)
        else:
            store[id] = clss(obj, time_delta)

        visible_objects[id] = store[id]

    return visible_objects


def get_association(
    object_bbox: np.ndarray,
    person_bbox: np.ndarray,
    lamb: float,
    extension: bool = False,
):
    object_centroid = bbox_centroid(object_bbox)
    person_centroid = bbox_centroid(person_bbox)

    if extension:
        person_bbox = extend_bbox(person_bbox)

    ioa = IoA(object_bbox, person_bbox)
    object_width = object_bbox[2] - object_bbox[0]
    centroid_distance = np.linalg.norm(
        np.array(object_centroid) - np.array(person_centroid)
    )

    return lamb * ioa + (1 - lamb) * (object_width / centroid_distance)


def check_overlap(
    object_bbox: np.ndarray, person_bbox: np.ndarray, extension: bool = False
):
    if extension:
        person_bbox = extend_bbox(person_bbox)
    return IoA(object_bbox, person_bbox) > 0


def extend_bbox(box: np.ndarray, pad: int = 20):
    box[0] -= pad
    box[1] -= pad
    box[2] += pad
    box[3] += pad
    return box


def get_close_persons(
    bag: Bag, object_cam: int, person_array: np.ndarray, radius: float
) -> list[int]:
    close_persons = person_array[person_array[:, 5] == object_cam]
    head_filter = close_persons[:, 1] < bag.data.centroids[object_cam][1]
    close_persons = close_persons[head_filter]
    person_centers = xyxy2xywh(close_persons)[:, 0:2]
    scaled_radius = radius * bag.data.diagonals[object_cam]
    distances = np.linalg.norm(
        person_centers - bag.data.centroids[object_cam][0:2],
        axis=1,
    )
    people_in_radius = distances < scaled_radius
    close_persons = close_persons[people_in_radius]

    if close_persons.size == 0:
        return []
    return close_persons[:, 4].astype(int).tolist()  # type: ignore
