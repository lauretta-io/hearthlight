from __future__ import annotations

from collections import defaultdict
import logging
import queue
import time
from threading import Thread

from shared.constants import FRAME_UPDATE_INTERVAL, FPS_INTERVAL, ModuleNames, QUEUE_TIMEOUT
from shared.models.DataModels import Status, StatusMessage, TrackInstance
from shared.rabbit_messenger import (
    BagPublisher,
    PersonPublisher,
    RoutingKey,
    StatusPublisher,
    get_reid_message_consumer,
)
from shared.slave import run_command_listener
from shared.utils.backpressure import summarize_queue_backpressure
from shared.utils.logger import set_run_logging
from shared.utils.runtime_guard import get_dead_thread_names
from shared.utils.timer import LoopTimer

logger = logging.getLogger(__name__)


class _OutputThread(Thread):
    def __init__(self):
        super().__init__(name=self.__class__.__name__, daemon=True)
        self.process = False
        self.queue = queue.Queue[tuple[dict[str, list[TrackInstance]], int]]()
        self.person_publisher = PersonPublisher()
        self.bag_publisher = BagPublisher()

    def run(self):
        self.process = True
        while self.process:
            try:
                tracks, frame_id = self.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                continue
            person_tracks = tracks.get("PERSON", [])
            for track in person_tracks:
                track.drop_tensors()
            self.person_publisher.publish_frame(person_tracks, {}, frame_id, {})
            bag_tracks = tracks.get("BAG", [])
            for track in bag_tracks:
                track.drop_tensors()
            self.bag_publisher.publish_frame(bag_tracks, {}, frame_id, {})
        self.person_publisher.close(clear_queue=True)
        self.bag_publisher.close(clear_queue=True)

    def stop(self):
        self.process = False


class PassthroughReID(Thread):
    def __init__(self, cfg, status_publisher: StatusPublisher):
        super().__init__(name=self.__class__.__name__, daemon=True)
        set_run_logging(cfg, module_name=ModuleNames.REID)
        self.process = False
        self.consumer = get_reid_message_consumer()
        self.output_thread = _OutputThread()
        self.status_publisher = status_publisher

    def run(self):
        self.process = True
        self.consumer.start()
        self.output_thread.start()
        timer = LoopTimer(log_interval=FPS_INTERVAL, task=ModuleNames.REID, abbrev="reid")
        timer.start()
        last_metrics_update = float("-inf")

        while self.process:
            dead_workers = get_dead_thread_names(
                {
                    "consumer": self.consumer,
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
                        extra={"reason": reason, "mode": "passthrough"},
                    )
                )
                self.process = False
                continue
            try:
                _, message = self.consumer.queue.get(timeout=QUEUE_TIMEOUT)
            except queue.Empty:
                continue
            timer.time("fetch")

            frame_info = message.get(RoutingKey.FRAME_INFO)
            track_message = message.get(RoutingKey.TRACK)
            if frame_info is None or track_message is None:
                continue

            grouped_tracks: dict[str, list[TrackInstance]] = defaultdict(list)
            for track in track_message.track_instances:
                track.real_id = int(track.track_id)
                track.confirmed = True
                grouped_tracks[str(track.clss).strip().upper()].append(track)

            self.output_thread.queue.put((grouped_tracks, frame_info.frame_id))
            current_time = time.time()
            if current_time - last_metrics_update > FRAME_UPDATE_INTERVAL:
                queue_depths = {
                    "consumer": self.consumer.queue.qsize(),
                    "output_thread": self.output_thread.queue.qsize(),
                }
                self.status_publisher.publish(
                    StatusMessage(
                        status=Status.INFO,
                        module=ModuleNames.REID,
                        extra={
                            "mode": "passthrough",
                            "queue_depths": queue_depths,
                            "backpressure": summarize_queue_backpressure(queue_depths),
                        },
                    )
                )
                last_metrics_update = current_time
            timer.loop()

        self.consumer.stop()
        self.output_thread.stop()
        self.consumer.join()
        self.output_thread.join()

    def stop(self):
        self.process = False


if __name__ == "__main__":
    run_command_listener(ModuleNames.REID, PassthroughReID)
