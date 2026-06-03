import queue
from collections import defaultdict
from threading import Thread
import logging
import time

from omegaconf import DictConfig
from sqlalchemy import func
import torch

from .output_threads import OutputThread

from .poi import POIManager
from hearthlight_model_zoo.reid import PersonReIDBundle
from ..shared.utils.model_registry import (
    MODEL_STAGE_REID,
    build_default_bindings,
    get_registration,
    load_registry_bundle,
)

from ..shared.utils.backpressure import summarize_queue_backpressure
from ..shared.utils.logger import set_run_logging
from ..shared.utils.runtime_guard import get_dead_thread_names
from ..shared.utils.timer import LoopTimer
from ..shared.slave import run_command_listener
from ..shared.database.database import SessionLocal
from ..shared.database.database_worker import DatabaseWorker
from ..shared.models.SQLModels import Person, Bag
from ..shared.models.DataModels import Status, TrackInstance, StatusMessage
from ..shared.constants import (
    QUEUE_TIMEOUT,
    FPS_INTERVAL,
    FRAME_UPDATE_INTERVAL,
    ModuleNames,
    DetectorClasses,
)
from ..shared.rabbit_messenger import (
    get_reid_message_consumer,
    StatusPublisher,
    RoutingKey,
)

logger = logging.getLogger(__name__)

PERSON = DetectorClasses.PERSON
BAG = DetectorClasses.BAG


def get_max_id(table):
    with SessionLocal() as db:
        return db.query(func.max(table.id)).scalar() or 0

def get_min_id(table):
    with SessionLocal() as db:
        return db.query(func.min(table.id)).scalar() or 0


def namespace_model_id(raw_id: int, namespace: int) -> int:
    if raw_id >= 0:
        return raw_id + namespace
    return raw_id - namespace


class LegacyReIDBundle:
    def __init__(self, cfg: DictConfig, registration: dict, namespace: int):
        self.namespace = namespace
        bundle = PersonReIDBundle(cfg, registration, namespace=namespace)
        self.person_reid = bundle.person_reid
        self.bag_reid = bundle.bag_reid

    def search(self, feature, max_matches: int, match_threshold: float) -> list[int]:
        candidate_ids = self.person_reid.strategy.vectors.get_nearest_ids(
            feature,
            max_matches,
            match_threshold,
        )
        return [
            namespace_model_id(candidate_id, self.namespace)
            for candidate_id in candidate_ids
        ]


REID_ADAPTERS = {
    "legacy_reid": LegacyReIDBundle,
    "transreid_person_hybrid_bag": LegacyReIDBundle,
}


class ReID(Thread):
    def __init__(self, cfg: DictConfig, status_publisher: StatusPublisher):
        super().__init__(name=self.__class__.__name__, daemon=True)

        set_run_logging(cfg, module_name=ModuleNames.REID)
        try:
            logger.debug("Initializing", extra={"task": self.name})
            self.process = False
            DatabaseWorker.set_run_id(cfg.run_id)

            # get the ids to start the reid ids from
            self.person_offset = get_max_id(Person)
            self.temp_person_offset = get_min_id(Person)
            self.bag_offset = get_max_id(Bag)
            self.temp_bag_offset = get_min_id(Bag)

            logger.debug("Initializing ReID Modules", extra={"task": self.name})
            self.registry_bundle = load_registry_bundle()
            defaults = build_default_bindings(
                self.registry_bundle,
                runtime_model_bindings=getattr(cfg, "model_bindings", None),
            )
            self.default_model_key = defaults.get(MODEL_STAGE_REID)
            self.camera_model_keys = {}
            self.reid_models = {}
            for model_index, (cam_id, camera_cfg) in enumerate(cfg.input.cameras.items()):
                camera_dict = dict(camera_cfg)
                model_key = camera_dict.get("reid_model_key") or self.default_model_key
                self.camera_model_keys[cam_id] = model_key
                if model_key in self.reid_models:
                    continue
                registration = get_registration(
                    self.registry_bundle,
                    MODEL_STAGE_REID,
                    model_key,
                )
                if registration is None:
                    raise ValueError(f"missing reid registration {model_key}")
                adapter_name = registration.get("adapter", "legacy_reid")
                adapter_cls = REID_ADAPTERS.get(adapter_name)
                if adapter_cls is None:
                    raise ValueError(f"unknown reid adapter {adapter_name}")
                namespace = model_index * 1_000_000
                self.reid_models[model_key] = adapter_cls(cfg, registration, namespace)

            primary_bundle = next(iter(self.reid_models.values()))
            self.person_reid = primary_bundle.person_reid
            self.bag_reid = primary_bundle.bag_reid

            logger.debug("Initialized ReID Modules", extra={"task": self.name})

            self.consumer = get_reid_message_consumer()

            self.poi_manager = POIManager(cfg, self.reid_models, self.person_offset)

            self.output_thread = OutputThread(cfg)
            self.status_publisher = status_publisher
            self.save_features = bool(cfg.output.features.save_features)
            self.clear_queues_on_stop = False
        except Exception:
            logger.exception("Failed to initialize", extra={"task": self.name})
            raise

        logger.debug("Initialized", extra={"task": self.name})

    def run(self):
        logger.info("Starting", extra={"task": self.name})

        self.process = True
        self.consumer.start()
        self.poi_manager.consumer.start()
        self.output_thread.start()

        ids_to_guess: dict[str, set[int]] = defaultdict(set)
        last_metrics_update = float("-inf")

        timer = LoopTimer(log_interval=FPS_INTERVAL, task=self.name, abbrev="reid")
        timer.start()

        while self.process:
            dead_workers = get_dead_thread_names(
                {
                    "consumer": self.consumer,
                    "poi_consumer": self.poi_manager.consumer,
                    "output_thread": self.output_thread,
                }
            )
            if dead_workers:
                reason = f"critical worker threads exited unexpectedly: {', '.join(dead_workers)}"
                logger.error(reason, extra={"task": self.name})
                self.status_publisher.publish(
                    StatusMessage(
                        status=Status.ERROR,
                        module=ModuleNames.REID,
                        extra={"reason": reason},
                    )
                )
                self.process = False
                continue
            try:
                frame_id, message = self.consumer.queue.get(timeout=QUEUE_TIMEOUT)
                frame_info = message.get(RoutingKey.FRAME_INFO)
                if frame_info is None:
                    logger.error("Frame info is None", extra={"task": self.name})
                    continue
            except queue.Empty:
                continue
            timer.time("fetch")

            tracks: dict[str, list[TrackInstance]] = defaultdict(list)
            _tracks = data.track_instances if (data := message.get(RoutingKey.TRACK)) else []
            for track in _tracks:
                tracks[track.clss].append(track)

            id_updates: dict[str, dict[int, int]] = defaultdict(dict)
            id_guesses: dict[int, int] = {}

            person_tracks = tracks.get(PERSON, [])
            person_tracks_by_model: dict[str, list[TrackInstance]] = defaultdict(list)
            for track in person_tracks:
                model_key = self.camera_model_keys.get(track.cam_id, self.default_model_key)
                person_tracks_by_model[model_key].append(track)

            for model_key, bundle_tracks in person_tracks_by_model.items():
                bundle = self.reid_models[model_key]
                bundle.person_reid.reid(bundle_tracks)
                person_ids = bundle.person_reid.entities.get_ids(bundle_tracks)
                for track, person_id in zip(bundle_tracks, person_ids):
                    namespaced_id = namespace_model_id(person_id, bundle.namespace)
                    if person_id > 0:
                        track.real_id = namespaced_id + self.person_offset
                        track.confirmed = True
                    else:
                        track.real_id = namespaced_id + self.temp_person_offset
                        ids_to_guess[model_key].add(person_id)

                    reid_entity = bundle.person_reid.entities.get(person_id)
                    if reid_entity is not None and reid_entity.feature_count > bundle.person_reid.min_features:
                        track.confirmed = True

                    if person_id in ids_to_guess[model_key] and track.confirmed:
                        id_guess = bundle.person_reid.predict(person_id)
                        if id_guess is not None:
                            guessed_id = namespace_model_id(id_guess, bundle.namespace)
                            id_guesses[track.real_id] = guessed_id + self.person_offset
                        ids_to_guess[model_key].discard(person_id)

                for temp_id in ids_to_guess[model_key].copy():
                    if not bundle.person_reid.entities.get(temp_id):
                        ids_to_guess[model_key].discard(temp_id)

                person_id_updates = bundle.person_reid.get_temp_to_real_update()
                for temp_id, real_id in person_id_updates.items():
                    id_updates[PERSON][
                        namespace_model_id(temp_id, bundle.namespace) + self.temp_person_offset
                    ] = namespace_model_id(real_id, bundle.namespace) + self.person_offset
            # if id_guesses:
            #     logger.info(f"ID guesses generated: {id_updates}", extra={"task": self.name})

            bag_tracks = tracks.get(BAG, [])
            bag_tracks_by_model: dict[str, list[TrackInstance]] = defaultdict(list)
            for track in bag_tracks:
                model_key = self.camera_model_keys.get(track.cam_id, self.default_model_key)
                bag_tracks_by_model[model_key].append(track)

            for model_key, bundle_tracks in bag_tracks_by_model.items():
                bundle = self.reid_models[model_key]
                bundle.bag_reid.reid(bundle_tracks)
                bag_ids = bundle.bag_reid.entities.get_ids(bundle_tracks)
                for track, bag_id in zip(bundle_tracks, bag_ids):
                    namespaced_id = namespace_model_id(bag_id, bundle.namespace)
                    if bag_id > 0:
                        track.real_id = namespaced_id + self.bag_offset
                        track.confirmed = True
                    else:
                        track.real_id = namespaced_id + self.temp_bag_offset

                bag_id_updates = bundle.bag_reid.get_temp_to_real_update()
                for temp_id, real_id in bag_id_updates.items():
                    id_updates[BAG][
                        namespace_model_id(temp_id, bundle.namespace) + self.temp_bag_offset
                    ] = namespace_model_id(real_id, bundle.namespace) + self.bag_offset
            if id_updates[BAG] or id_updates[PERSON]:
                logger.info(f"ID updates generated: {id_updates}", extra={"task": self.name})
            timer.time("reid")

            poi_results = []
            poi_results = self.poi_manager.update()
            timer.time("poi")

            self.output_thread.queue.put((tracks, id_updates, id_guesses, poi_results, frame_info))
            current_time = time.time()
            if current_time - last_metrics_update > FRAME_UPDATE_INTERVAL:
                queue_depths = {
                    "consumer": self.consumer.queue.qsize(),
                    "poi_consumer": self.poi_manager.consumer.queue.qsize(),
                    "output_thread": self.output_thread.queue.qsize(),
                    "rabbit_thread": self.output_thread.rabbit_thread.queue.qsize(),
                    "database_thread": self.output_thread.database_thread.queue.qsize(),
                }
                if self.save_features:
                    queue_depths["feature_save_thread"] = self.output_thread.feature_save_thread.queue.qsize()
                self.status_publisher.publish(
                    StatusMessage(
                        status=Status.INFO,
                        module=ModuleNames.REID,
                        extra={
                            "queue_depths": queue_depths,
                            "backpressure": summarize_queue_backpressure(queue_depths),
                        },
                    )
                )
                last_metrics_update = current_time

            timer.loop()

        self.consumer.stop(clear_queues=self.clear_queues_on_stop)
        self.poi_manager.consumer.stop(clear_queues=self.clear_queues_on_stop)
        self.output_thread.stop(clear_queues=self.clear_queues_on_stop)
        self.consumer.join()
        self.poi_manager.consumer.join()
        self.output_thread.join()

        try:
            torch.cuda.empty_cache()
        except Exception:
            logger.exception("Failed to empty torch cuda cache", extra={"task": self.name})
        logger.info("Stopped", extra={"task": self.name})

    def stop(self):
        logger.info("Stopping", extra={"task": self.name})
        self.clear_queues_on_stop = True
        self.process = False


if __name__ == "__main__":
    run_command_listener(ModuleNames.REID, ReID)
