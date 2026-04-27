import queue
from threading import Thread
import logging
import time

from omegaconf import DictConfig

from .output_threads import OutputThread
from .object_classes import TrackedObject
from .incident_classes import Incident
from .manager_classes import (
    PersonManager,
    BagManager,
    GunManager,
)
from shared.rabbit_messenger import (
    get_association_message_consumer,
    ResolutionConsumer,
    StatusPublisher,
    RoutingKey,
)
from shared.models.DataModels import Status, StatusMessage
from shared.utils.backpressure import summarize_queue_backpressure
from shared.utils.timer import LoopTimer
from shared.utils.runtime_guard import get_dead_thread_names
from shared.slave import run_command_listener
from shared.utils.logger import set_run_logging
from shared.constants import (
    QUEUE_TIMEOUT,
    FPS_INTERVAL,
    FRAME_UPDATE_INTERVAL,
    STREAM_MESSAGES_PER_FRAME,
    Tasks,
    ModuleNames,
)

logger = logging.getLogger(__name__)


class Association(Thread):
    def __init__(self, cfg: DictConfig, status_publisher: StatusPublisher):
        super().__init__(name=self.__class__.__name__, daemon=True)

        set_run_logging(cfg, module_name=ModuleNames.ASSOCIATION)

        try:
            logger.debug("Initializing", extra={"task": self.name})

            self.person_manager = PersonManager(cfg)
            self.incident_manager = self.person_manager.incidents
            self.bag_manager = BagManager(
                cfg, self.person_manager, self.incident_manager
            )
            self.gun_manager = GunManager(
                cfg, self.person_manager, self.incident_manager
            )
            self.consumer = get_association_message_consumer(cfg)
            self.resolution_consumer = ResolutionConsumer()
            self.output_thread = OutputThread(cfg)

            TrackedObject.set_cam_refresh_interval(cfg.journey.time_to_end)

            self.status_publisher = status_publisher
        except Exception:
            logger.exception("Failed to initialize", extra={"task": self.name})
            raise

        logger.debug("Initialized", extra={"task": self.name})

    def run(self):
        logger.info("Starting", extra={"task": self.name})

        self.process = True
        self.consumer.start()
        self.resolution_consumer.start()
        self.output_thread.start()

        timer = LoopTimer(
            log_interval=FPS_INTERVAL, task=ModuleNames.ASSOCIATION, abbrev="ass."
        )
        timer.start()
        last_metrics_update = float("-inf")

        while self.process:
            dead_workers = get_dead_thread_names(
                {
                    "consumer": self.consumer,
                    "resolution_consumer": self.resolution_consumer,
                    "output_thread": self.output_thread,
                }
            )
            if dead_workers:
                reason = f"critical worker threads exited unexpectedly: {', '.join(dead_workers)}"
                logger.error(reason, extra={"task": self.name})
                self.status_publisher.publish(
                    StatusMessage(
                        status=Status.ERROR,
                        module=ModuleNames.ASSOCIATION,
                        extra={"reason": reason},
                    )
                )
                self.process = False
                continue
            external_resolutions = []
            for _ in range(STREAM_MESSAGES_PER_FRAME):
                try:
                    external_resolution = self.resolution_consumer.queue.get_nowait()
                    external_resolutions.append(external_resolution)
                except queue.Empty:
                    continue

            try:
                frame_id, message = self.consumer.queue.get(timeout=QUEUE_TIMEOUT)
                frame_info = message.get(RoutingKey.FRAME_INFO)
                if frame_info is None:
                    logger.error("Frame info is None", extra={"task": self.name})
                    continue
            except queue.Empty:
                continue

            tracks = data.track_instances if (data := message.get(Tasks.PERSON)) else []
            id_updates = data.id_updates if (data := message.get(Tasks.PERSON)) else {}
            id_guesses = data.id_guesses if (data := message.get(Tasks.PERSON)) else {}

            bag_tracks = (
                data.track_instances if (data := message.get(Tasks.BAG)) else []
            )
            bag_id_updates = data.id_updates if (data := message.get(Tasks.BAG)) else {}
            gun_detections = data.detections if (data := message.get(Tasks.GUN)) else []
            timer.time("fetch")

            self.person_manager.update(tracks, id_updates, id_guesses, frame_info)
            self.bag_manager.update(bag_tracks, bag_id_updates, frame_info)
            timer.time("update")

            bag_owner_pairs = self.bag_manager.get_new_bag_owners(frame_info)
            if bag_owner_pairs:
                logger.info("Bag owner pairs: %s", bag_owner_pairs, extra={"task": self.name})
            timer.time("bag owner pairs")

            new_incidents: list[Incident] = []
            new_incidents += self.bag_manager.get_new_unattended_bags()
            timer.time("unattended bags")
            new_incidents += self.gun_manager.get_new_gunmen(gun_detections, frame_info)
            timer.time("gunmen")
            system_resolutions = self.incident_manager.update(
                new_incidents, external_resolutions
            )
            self.incident_manager.update_ids(id_updates)
            timer.time("incidents update")
            if new_incidents:
                logger.info("New incidents: %s", new_incidents, extra={"task": self.name})

            self.output_thread.queue.put(
                (bag_owner_pairs, new_incidents, system_resolutions)
            )
            current_time = time.time()
            if current_time - last_metrics_update > FRAME_UPDATE_INTERVAL:
                queue_depths = {
                    "consumer": self.consumer.queue.qsize(),
                    "resolution_consumer": self.resolution_consumer.queue.qsize(),
                    "output_thread": self.output_thread.queue.qsize(),
                }
                self.status_publisher.publish(
                    StatusMessage(
                        status=Status.INFO,
                        module=ModuleNames.ASSOCIATION,
                        extra={
                            "queue_depths": queue_depths,
                            "backpressure": summarize_queue_backpressure(queue_depths),
                        },
                    )
                )
                last_metrics_update = current_time

            timer.loop()

        self.consumer.stop()
        self.resolution_consumer.stop()
        self.output_thread.stop()
        self.consumer.join()
        self.resolution_consumer.join()
        self.output_thread.join()
        logger.info("Stopped", extra={"task": self.name})

    def stop(self):
        self.process = False


if __name__ == "__main__":
    run_command_listener(ModuleNames.ASSOCIATION, Association)
