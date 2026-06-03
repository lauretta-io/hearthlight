from threading import Thread
import queue
import os
import logging

import numpy as np

from .journey import JourneyTracker
from .loitering import LoiteringManager
from ..shared.database.database_worker import DatabaseWorker
from ..shared.models.DataModels import TrackInstance, POIResult, Frames, JourneyNode
from ..shared.utils.zones import ZoneManager
from ..shared.constants import QUEUE_TIMEOUT, DetectorClasses
from ..shared.rabbit_messenger import PersonPublisher, BagPublisher

logger = logging.getLogger(__name__)

PERSON = DetectorClasses.PERSON
BAG = DetectorClasses.BAG


class OutputThread(Thread):
    def __init__(self, cfg):
        super().__init__(name=self.__class__.__name__)
        logger.debug("Initializing", extra={"task": self.name})

        self.process = False
        self.queue = queue.Queue[
            tuple[
                dict[str, list[TrackInstance]],
                dict[str, dict[int, int]],
                dict[int, int],
                list[POIResult],
                Frames,
            ]
        ]()
        self.database_thread = DatabaseThread()
        self.clear_queues_on_stop = False
        self.rabbit_thread = RabbitThread()
        cameras = DatabaseWorker.get_cameras()
        self.zone_manager = ZoneManager(cameras, cfg.passenger_zones)
        self.journey_tracker = JourneyTracker(cfg)
        self.loitering_manager = LoiteringManager(
            threshold=cfg.get("loitering_threshold", 600.0)
        )
        self.save_features = cfg.output.features.save_features
        if self.save_features:
            self.feature_save_thread = FeatureSaveThread(cfg)
            self.feature_index = 0

        logger.debug("Initialized", extra={"task": self.name})

    def run(self):
        logger.info("Starting", extra={"task": self.name})

        self.process = True
        self.rabbit_thread.start()
        self.database_thread.start()
        if self.save_features:
            self.feature_save_thread.start()

        while self.process:
            try:
                tracks, id_updates, id_guesses, poi_results, frame_info = (
                    self.queue.get(timeout=QUEUE_TIMEOUT)
                )
            except queue.Empty:
                continue

            if self.save_features:
                features = []
                for track in tracks.get(PERSON, []):
                    if track.feature is not None:
                        features.append(track.feature)
                        track.feature_id = self.feature_index
                        self.feature_index += 1
                self.feature_save_thread.queue.put(features)

            new_nodes: list[JourneyNode] = []

            person_tracks = tracks.get(PERSON, [])
            bag_tracks = tracks.get(BAG, [])
            all_tracks = person_tracks + bag_tracks

            self.zone_manager.add_zones(all_tracks)
            for track in all_tracks:
                if not track.confirmed:
                    continue
                journey_node = self.journey_tracker.update(track)
                if journey_node is not None:
                    new_nodes.append(journey_node)

            finished_nodes = self.journey_tracker.get_finished_nodes(frame_info)

            for track in person_tracks:
                if track.confirmed:
                    self.loitering_manager.update([track])

            person_id_updates = id_updates.get(PERSON, {})
            for temp_id, real_id in person_id_updates.items():
                self.loitering_manager.merge(temp_id, real_id)

            loitering_incidents = self.loitering_manager.get_new_loiterers()

            if person_tracks:
                latest_ts = max(t.timestamp for t in person_tracks)
                self.loitering_manager.evict_stale(cutoff=latest_ts - 300.0)

            self.rabbit_thread.queue.put((tracks, id_updates, id_guesses, frame_info))
            self.database_thread.queue.put(
                (tracks, id_updates, poi_results, new_nodes, finished_nodes, loitering_incidents)
            )

        self.rabbit_thread.stop(clear_queues=self.clear_queues_on_stop)
        self.database_thread.stop()
        if self.save_features:
            self.feature_save_thread.stop()
        self.rabbit_thread.join()
        self.database_thread.join()
        if self.save_features:
            self.feature_save_thread.join()

        logger.info("Stopped", extra={"task": self.name})

    def stop(self, clear_queues: bool = False):
        logger.info("Stopping", extra={"task": self.name})
        self.clear_queues_on_stop = clear_queues
        self.process = False


class RabbitThread(Thread):
    def __init__(self):
        super().__init__(name=self.__class__.__name__)
        self.queue = queue.Queue[
            tuple[
                dict[str, list[TrackInstance]],
                dict[str, dict[int, int]],
                dict[int, int],
                Frames,
            ]
        ]()
        self.person_publisher = PersonPublisher()
        self.bag_publisher = BagPublisher()
        self.process = False
        self.clear_queues_on_stop = False

    def run(self):
        logger.debug("Starting", extra={"task": self.name})
        self.process = True
        while self.process:
            try:
                tracks, id_updates, id_guesses, frame_info = self.queue.get(
                    timeout=QUEUE_TIMEOUT
                )
            except queue.Empty:
                continue

            person_tracks = tracks.get(PERSON, [])
            person_id_updates = id_updates.get(PERSON, {})
            for track in person_tracks:
                track.drop_tensors()
            self.person_publisher.publish_frame(
                person_tracks, person_id_updates, frame_info.frame_id, id_guesses
            )

            bag_tracks = tracks.get(BAG, [])
            bag_id_updates = id_updates.get(BAG, {})
            for track in bag_tracks:
                track.drop_tensors()
            self.bag_publisher.publish_frame(
                bag_tracks, bag_id_updates, frame_info.frame_id
            )

        self.person_publisher.close(clear_queue=self.clear_queues_on_stop)
        self.bag_publisher.close(clear_queue=self.clear_queues_on_stop)

        logger.debug("Stopped", extra={"task": self.name})

    def stop(self, clear_queues: bool = False):
        logger.debug("Stopping", extra={"task": self.name})
        self.clear_queues_on_stop = clear_queues
        self.process = False


class DatabaseThread(Thread):
    def __init__(self):
        super().__init__(name=self.__class__.__name__)
        self.queue = queue.Queue[
            tuple[
                dict[str, list[TrackInstance]],
                dict[str, dict[int, int]],
                list[POIResult],
                list[JourneyNode],
                list[JourneyNode],
                list,
            ]
        ]()
        self.database_publisher = DatabaseWorker()
        self.process = False

    def run(self):
        logger.debug("Starting", extra={"task": self.name})
        self.process = True
        while self.process:
            try:
                tracks, id_updates, poi_results, new_nodes, finished_nodes, loitering_incidents = (
                    self.queue.get(timeout=QUEUE_TIMEOUT)
                )
            except queue.Empty:
                continue

            self.database_publisher.publish_id_updates(id_updates)
            self.database_publisher.publish_reid_data(tracks)
            self.database_publisher.publish_journey_data(new_nodes, finished_nodes)
            self.database_publisher.publish_poi_data(poi_results)
            self.database_publisher.publish_loitering_incidents(loitering_incidents)

        logger.debug("Stopped", extra={"task": self.name})

    def stop(self):
        logger.debug("Stopping", extra={"task": self.name})
        self.process = False


class FeatureSaveThread(Thread):
    BATCH_SIZE = 10000

    def __init__(self, cfg):
        super().__init__(name=self.__class__.__name__)
        self.process = False
        self.queue = queue.Queue[list[np.ndarray]]()
        self.directory = cfg.output.features.feature_dir
        self.save_count = 1
        os.makedirs(self.directory)

    def run(self):
        logger.debug("Starting", extra={"task": self.name})
        self.process = True
        feature_list = []
        while self.process:
            try:
                features = self.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                continue

            feature_list += features

            if len(feature_list) > FeatureSaveThread.BATCH_SIZE:
                self.save(feature_list)
                feature_list = []

        if feature_list:
            self.save(feature_list)

        logger.debug("Stopped", extra={"task": self.name})

    def save(self, features):
        filename = f"{self.save_count}.npy"
        with open(os.path.join(self.directory, filename), "wb") as file:
            np.save(file, np.array(features))
        self.save_count += 1
        total = self.save_count * FeatureSaveThread.BATCH_SIZE
        logger.debug(
            f"Saved batch {self.save_count} (~ {total} total features)",
            extra={"task": self.name},
        )

    def stop(self):
        logger.debug("Stopping", extra={"task": self.name})
        self.process = False
